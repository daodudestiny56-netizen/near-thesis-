"""One-off enrichment: add `total_supply` and `protocol_version` to months collected before the collector stored them.

The values come from the cached `/v0/block` responses of the very same sampled blocks (nothing new is requested). Months collected
after the collector was updated already contain both columns, so this is idempotent. Run `python -m census merge` afterwards.
"""
from __future__ import annotations

import json
import sqlite3
import zlib

import pandas as pd

from . import config as C
from .client import CACHE_PATH, Client
from .collect import BY_PERIOD


def run() -> None:
    db = sqlite3.connect(str(CACHE_PATH))
    key = Client._key
    filled = 0
    for path in sorted(BY_PERIOD.glob("*_blocks.csv")):
        df = pd.read_csv(path)
        if {"total_supply", "protocol_version"} <= set(df.columns):
            continue
        sup, ver = [], []
        for h in df["height"]:
            row = db.execute("SELECT v FROM http WHERE k=?", (key("block", {"block_id": int(h), "with_transactions": True}),)).fetchone()
            if not row:
                raise SystemExit(f"{path.name}: block {h} is not in the cache; re-run `python -m census collect` for that month")
            b = json.loads(zlib.decompress(row[0]))["block"]
            sup.append(int(b["total_supply"]) / 1e24)
            ver.append(b["protocol_version"])
        df["total_supply"], df["protocol_version"] = sup, ver
        df.to_csv(path, index=False)
        filled += 1
    print(f"enriched {filled} month files")


if __name__ == "__main__":
    run()
