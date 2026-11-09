"""Build the validation label set from evidence the classifier never sees.

  human      the account recently WROTE to NEAR Social (social.near `set`) and has a profile name there - an
             on-chain identity a person wrote about themselves - and does not look like infrastructure.
             (A transaction-weighted sample contains almost no such accounts, so humans are sourced here
             independently of the sample and profiled separately.)
  automated  the account id declares an automated role (bot, relayer, keeper, oracle, solver, ...) or is a
             documented piece of infrastructure.

`harvest` produces candidates; a person then reviews them (data/labels/review_notes.md records what was
removed and why) and the reviewed result is committed as data/labels/labels.csv.

Known biases, stated plainly: human labels over-represent people engaged enough to fill in a profile, and
automated labels over-represent bots that announce themselves. Accuracy measured on these labels is
therefore optimistic for stealthy bots and for anonymous humans. METHODOLOGY.md repeats this.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

from . import config as C
from .client import Client
from .features import history_features
from .heights import latest_height

RPC = "https://rpc.mainnet.near.org"
SOCIAL_CACHE = C.ROOT / "data" / "cache" / "social_profiles.json"
BOT_TOKENS = {"bot", "bots", "relay", "relayer", "keeper", "oracle", "solver", "worker", "agent", "indexer",
              "cron", "harvester", "liquidator", "arb", "sniper", "scheduler", "automation", "autocompound"}


def name_tokens(account: str) -> set[str]:
    return {t for t in re.split(r"[._\-\d]+", account.lower()) if t}


def looks_automated(account: str) -> bool:
    return bool(name_tokens(account) & BOT_TOKENS)


def _social_get(keys: list[str]) -> dict:
    args = base64.b64encode(json.dumps({"keys": keys}).encode()).decode()
    body = {"jsonrpc": "2.0", "id": 1, "method": "query", "params": {
        "request_type": "call_function", "finality": "final", "account_id": "social.near",
        "method_name": "get", "args_base64": args}}
    delay = 2.0
    for _ in range(6):
        try:
            req = urllib.request.Request(RPC, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            if "result" in r and "result" in r["result"]:
                return json.loads(bytes(r["result"]["result"]))
        except Exception:
            pass
        time.sleep(delay)
        delay *= 2
    return {}


def profiles(accounts: list[str], batch: int = 40) -> dict[str, str]:
    """account -> profile name ('' when none). Cached on disk."""
    cache = json.loads(SOCIAL_CACHE.read_text()) if SOCIAL_CACHE.exists() else {}
    todo = [a for a in accounts if a not in cache]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        got = _social_get([f"{a}/profile/name" for a in chunk])
        for a in chunk:
            name = (got.get(a) or {}).get("profile", {}).get("name", "")
            cache[a] = name if isinstance(name, str) else ""
        if (i // batch) % 10 == 0:
            SOCIAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
            SOCIAL_CACHE.write_text(json.dumps(cache))
            print(f"  profiles {min(i + batch, len(todo))}/{len(todo)}", flush=True)
    SOCIAL_CACHE.write_text(json.dumps(cache))
    return {a: cache[a] for a in accounts}


def social_writers(client: Client, pages: int = 15) -> list[str]:
    """Real signers of recent `set` calls on social.near (posts, comments, profile edits)."""
    hashes, token = [], None
    for _ in range(pages):
        body = {"account_id": "social.near", "is_function_call": True, "desc": True, "limit": 200}
        if token:
            body["resume_token"] = token
        res = client.post("account", body)
        hashes += [r["transaction_hash"] for r in res.get("account_txs", [])]
        token = res.get("resume_token")
        if not token:
            break
    writers = []
    for i in range(0, len(hashes), 20):
        for full in client.transactions(hashes[i:i + 20]):
            tx = full["transaction"]
            actions = tx.get("actions", [])
            who = tx["signer_id"]
            if len(actions) == 1 and "Delegate" in actions[0]:      # relayed: the user is the delegate sender
                who = actions[0]["Delegate"]["delegate_action"]["sender_id"]
            if tx.get("receiver_id") == "social.near" or who != tx["signer_id"]:
                writers.append(who)
    return sorted(set(writers))


def harvest() -> pd.DataFrame:
    client = Client()
    txs = pd.read_csv(C.DERIVED / "sample_txs.csv.gz", usecols=["real_signer"])
    sample_accounts = sorted(txs["real_signer"].unique())
    print(f"{len(sample_accounts):,} distinct signers in the sample")
    writers = social_writers(client)
    print(f"{len(writers):,} distinct recent social.near writers")
    prof = profiles(sorted(set(sample_accounts) | set(writers)))
    rows = []
    for a in sample_accounts:                       # bots announce themselves in their names
        if looks_automated(a) and not prof.get(a):
            rows.append((a, "automated", "declared_role_in_name", f"id tokens: {sorted(name_tokens(a) & BOT_TOKENS)}"))
    for a in writers:                               # people write profiles and posts
        name = prof.get(a, "")
        if name and not looks_automated(a):
            rows.append((a, "human", "social_writer_with_profile", f"wrote to social.near; profile name {name[:50]!r}"))
    df = pd.DataFrame(rows, columns=["account", "label", "evidence_type", "evidence"]).drop_duplicates("account")
    df.to_csv(C.LABELS / "candidates.csv", index=False)
    print(df["label"].value_counts().to_string())
    return df


def label_features(labels: pd.DataFrame) -> pd.DataFrame:
    """Behavioural features for label accounts that are not in the sample, as of the current chain head."""
    client = Client()
    acc = pd.read_csv(C.DERIVED / "account_features.csv.gz", low_memory=False)
    have = set(acc.loc[acc["role"] == "real", "account"])
    todo = [a for a in labels["account"] if a not in have]
    head = latest_height(client) + 1
    rows = []
    for k, a in enumerate(todo, 1):
        res = client.post("account", {"account_id": a, "is_real_signer": True, "desc": True,
                                      "limit": C.HISTORY_LIMIT, "to_tx_block_height": head})
        rows.append({"period": "label-time", "account": a, "role": "real",
                     **history_features(res.get("account_txs", []), res.get("txs_count"))})
        if k % 25 == 0:
            print(f"  label features {k}/{len(todo)}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(C.LABELS / "label_features.csv", index=False)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "harvest"
    if cmd == "harvest":
        harvest()
    elif cmd == "features":
        label_features(pd.read_csv(C.LABELS / "labels.csv"))
