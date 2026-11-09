"""Stage 1 - collect: draw random blocks per month, then profile every signer found in them.

For each calendar month:
  1. resolve the month's block-height range
  2. draw BLOCKS_PER_PERIOD blocks uniformly at random (seeded)  -> unbiased sample of transactions
  3. for each transaction, take the *real* signer (resolves relayed / meta-transactions) and the fee payer
  4. pull each distinct account's last 200 signed transactions before month-end  -> behavioural features
  5. fetch a bounded number of full transactions                  -> call shape, intents use, FC-key shape
Results land in data/derived/by_period/<month>_*.csv; `merge` folds them into the committed tables.
"""
from __future__ import annotations

import concurrent.futures as cf
import gzip
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import config as C
from .client import Client
from .features import history_features, tx_shape
from .heights import height_at, latest_height, to_ns

BY_PERIOD = C.DERIVED / "by_period"
WORKERS = 3


def month_ranges(first: str, now: datetime | None = None) -> list[tuple[str, datetime, datetime]]:
    now = now or datetime.now(timezone.utc)
    y, m = map(int, first.split("-"))
    out = []
    while (y, m) <= (now.year, now.month):
        start = datetime(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = datetime(ny, nm, 1)
        if (y, m) == (now.year, now.month):
            end = now.replace(tzinfo=None) - pd.Timedelta(minutes=10)
        out.append((f"{y:04d}-{m:02d}", start, end))
        y, m = ny, nm
    return out


def _paths(label: str) -> dict[str, Path]:
    return {k: BY_PERIOD / f"{label}_{k}.csv" for k in ("txs", "accounts", "blocks")}


def collect_period(client: Client, label: str, start: datetime, end: datetime, latest: int,
                   n_blocks: int = C.BLOCKS_PER_PERIOD) -> None:
    paths = _paths(label)
    if all(p.exists() for p in paths.values()):
        print(f"[{label}] already collected", flush=True)
        return
    t0 = time.time()
    s_h = height_at(client, to_ns(start), latest)
    e_h = height_at(client, to_ns(end), latest)
    rng = random.Random(f"{C.SEED}-{label}")
    heights = sorted(rng.sample(range(s_h, e_h), min(n_blocks, e_h - s_h)))

    # 2. sampled blocks -------------------------------------------------------------------------
    def fetch_block(h):
        return h, client.block(h, with_transactions=True)

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        fetched = list(ex.map(fetch_block, heights))
    blocks, txs = [], []
    for h, res in fetched:
        if not res:                      # skipped height: no block was produced, so nothing to sample
            continue
        b = res["block"]
        blocks.append({"period": label, "height": h, "ts": int(b["block_timestamp"]) // 10**9,
                       "num_tx": b["num_transactions"], "tokens_burnt": int(b["tokens_burnt"]) / 1e24,
                       "gas_burnt": int(b["gas_burnt"])})
        for t in res.get("block_txs", []):
            txs.append({
                "period": label, "height": h, "ts": int(t["tx_block_timestamp"]) // 10**9,
                "hash": t["transaction_hash"], "payer": t["signer_id"],
                "real_signer": t.get("real_signer_id") or t["signer_id"],
                "receiver": t["receiver_id"], "real_receiver": t.get("real_receiver_id") or t["receiver_id"],
                "relayed": bool(t.get("is_relayed")), "success": bool(t.get("is_success")),
                "fee_near": int(t["tokens_burnt"]) / 1e24, "gas_burnt": int(t["gas_burnt"]),
                "pubkey": t.get("signer_public_key", ""),
            })
    tx_df = pd.DataFrame(txs)
    print(f"[{label}] heights {s_h}-{e_h}: {len(blocks)} blocks, {len(txs)} txs "
          f"({time.time() - t0:.0f}s)", flush=True)

    # 4. per-account behavioural history -------------------------------------------------------------
    jobs = {}                                           # (account, role) -> None
    if len(tx_df):
        for a in tx_df["real_signer"].unique():
            jobs[(a, "real")] = None
        for a in tx_df.loc[tx_df["payer"] != tx_df["real_signer"], "payer"].unique():
            jobs[(a, "top")] = None

    def profile(job):
        account, role = job
        res = client.post("account", {
            "account_id": account, "desc": True, "limit": C.HISTORY_LIMIT, "to_tx_block_height": e_h,
            **({"is_real_signer": True} if role == "real" else {"is_signer": True}),
        })
        f = history_features(res.get("account_txs", []), res.get("txs_count"))
        return {"period": label, "account": account, "role": role, **f}

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        acct_rows = list(ex.map(profile, list(jobs)))
    print(f"[{label}] profiled {len(acct_rows)} accounts ({time.time() - t0:.0f}s)", flush=True)

    # 5. call shape for a bounded subsample of full transactions ------------------------------------
    shape_cols = ["n_actions", "delegated", "kind", "method", "touches_intents", "fc_key_consistent"]
    for c in shape_cols:
        tx_df[c] = None
    if len(tx_df):
        pick = tx_df.groupby("real_signer").head(C.FULL_TX_PER_SIGNER)      # at most N txs per signer
        pick = pick.sample(min(len(pick), C.FULL_TX_PER_PERIOD_CAP), random_state=C.SEED)
        hashes = list(pick["hash"])
        batches = [hashes[i:i + 20] for i in range(0, len(hashes), 20)]
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            fulls = [f for chunk in ex.map(client.transactions, batches) for f in chunk]
        shapes = {f["transaction"]["hash"]: tx_shape(f) for f in fulls}
        idx = tx_df["hash"].map(shapes.get)
        for c in shape_cols:
            tx_df[c] = idx.map(lambda s, c=c: s[c] if isinstance(s, dict) else None)
    print(f"[{label}] call shapes for {tx_df['kind'].notna().sum() if len(tx_df) else 0} txs "
          f"({time.time() - t0:.0f}s total, {client.network_calls} net calls so far)", flush=True)

    BY_PERIOD.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(acct_rows).to_csv(paths["accounts"], index=False)
    pd.DataFrame(blocks).to_csv(paths["blocks"], index=False)
    tx_df.to_csv(paths["txs"], index=False)          # written last: marks the month complete


def merge() -> None:
    """Fold per-month files into the three committed tables."""
    for kind, name in (("txs", "sample_txs"), ("accounts", "account_features"), ("blocks", "sample_blocks")):
        files = sorted(BY_PERIOD.glob(f"*_{kind}.csv"))
        if not files:
            continue
        df = pd.concat([pd.read_csv(f, low_memory=False) for f in files], ignore_index=True)
        out = C.DERIVED / f"{name}.csv.gz"
        with gzip.open(out, "wt", newline="") as fh:
            df.to_csv(fh, index=False)
        print(f"merged {len(files)} months -> {out.name}: {len(df):,} rows")


def run(first: str = C.FIRST_PERIOD, last: str | None = None, blocks: int = C.BLOCKS_PER_PERIOD) -> None:
    client = Client()
    latest = latest_height(client)
    months = month_ranges(first)
    if last:
        months = [m for m in months if m[0] <= last]
    months = [m for m in months if m[0] >= C.DENSE_FROM or (int(m[0][5:]) - 1) % C.SPARSE_STRIDE == 0]
    print(f"collecting {len(months)} months, newest first; {client.rps:.1f} req/s "
          f"({'API key' if client.api_key else 'anonymous'})", flush=True)
    for label, start, end in reversed(months):
        try:
            collect_period(client, label, start, end, latest, blocks)
        except Exception as e:                           # keep going; the month is retried on the next run
            print(f"[{label}] FAILED: {e}", file=sys.stderr, flush=True)
    merge()
