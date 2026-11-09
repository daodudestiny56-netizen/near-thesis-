"""Build the validation label set from evidence the classifier never sees.

  human      the account has a NEAR Social (SocialDB) profile with a name - an on-chain identity a person
             wrote about themselves - and does not look like infrastructure.
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


def harvest() -> pd.DataFrame:
    txs = pd.read_csv(C.DERIVED / "sample_txs.csv.gz", usecols=["real_signer"])
    accounts = sorted(txs["real_signer"].unique())
    print(f"{len(accounts):,} distinct signers in the sample")
    prof = profiles(accounts)
    rows = []
    for a in accounts:
        name = prof.get(a, "")
        bot = looks_automated(a)
        if name and not bot:
            rows.append((a, "human", "social_profile", f"NEAR Social profile name: {name[:60]!r}"))
        elif bot and not name:
            rows.append((a, "automated", "declared_role_in_name", f"id tokens: {sorted(name_tokens(a) & BOT_TOKENS)}"))
    df = pd.DataFrame(rows, columns=["account", "label", "evidence_type", "evidence"])
    out = C.LABELS / "candidates.csv"
    df.to_csv(out, index=False)
    print(df["label"].value_counts().to_string())
    return df


if __name__ == "__main__":
    harvest()
