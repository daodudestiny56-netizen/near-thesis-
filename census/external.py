"""External data: NEAR Intents fees and revenue, and the NEAR price, from DefiLlama's public API (no key needed).

`python -m census external` downloads a snapshot into data/external/ together with the retrieval time and DefiLlama's own
methodology text. The analysis reads only the committed snapshot, so `reproduce` stays offline and byte-identical; refreshing is
an explicit, separate step.

What the figures mean (quoted from DefiLlama's methodology, stored verbatim in the snapshot):
  Fees     gross fees charged on NEAR Intents swaps (protocol fee plus each frontend's affiliate fee, across integrators)
  Revenue  NEAR's net captured revenue, measured as NEAR/wNEAR swept into its revenue wallets
These are third-party figures, not measured by this repository.
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timezone

from . import config as C

EXTERNAL = C.ROOT / "data" / "external"
LLAMA = "https://api.llama.fi/summary/fees/near-intents"
COINS = "https://coins.llama.fi/chart/coingecko:near"
UA = {"User-Agent": "near-agent-census/1.0"}


def _get(url: str) -> dict:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"could not fetch {url}")


def _day(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d")


def run() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    fees = _get(f"{LLAMA}?dataType=dailyFees")
    rev = _get(f"{LLAMA}?dataType=dailyRevenue")
    snap = {
        "source": "DefiLlama /summary/fees/near-intents", "retrieved_on": now,
        "methodology": fees.get("methodology"), "methodologyURL": fees.get("methodologyURL"),
        "fees_usd": {_day(t): v for t, v in fees["totalDataChart"]},
        "revenue_usd": {_day(t): v for t, v in rev["totalDataChart"]},
    }
    (EXTERNAL / "defillama_near_intents.json").write_text(json.dumps(snap, indent=1, sort_keys=True))

    first = min(snap["fees_usd"])
    start = int(datetime.fromisoformat(first).replace(tzinfo=timezone.utc).timestamp()) - 86400 * 31   # a month of margin before the first fee day
    prices: dict[str, float] = {}
    while start < time.time():
        d = _get(f"{COINS}?start={start}&span=500&period=1d")["coins"]["coingecko:near"]["prices"]
        for p in d:
            prices[_day(p["timestamp"])] = p["price"]
        if len(d) < 2:
            break
        start = int(d[-1]["timestamp"]) + 86400
        if len(d) < 500:
            break
    (EXTERNAL / "defillama_near_price.json").write_text(json.dumps(
        {"source": "DefiLlama coins API, coingecko:near, daily", "retrieved_on": now, "usd": prices}, indent=1, sort_keys=True))
    print(f"snapshot {now}: Intents fees/revenue days {len(snap['fees_usd'])}/{len(snap['revenue_usd'])} ({first} to {max(snap['fees_usd'])}), "
          f"NEAR price days {len(prices)}")


if __name__ == "__main__":
    run()
