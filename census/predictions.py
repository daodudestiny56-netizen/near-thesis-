"""Pre-registered predictions: frozen once, hashed, timestamped, and checkable by anyone.

`python -m census predictions --freeze`   write predictions/predictions.csv (refuses to overwrite) and its SHA-256
`python -m census predictions`            verify the hash, then show each prediction's baseline and, if the data exist, its outcome

Each prediction is a threshold on a quantity this census already measures, for the **2026-12 sample** (or the third-party Intents revenue
series), with the baseline at freeze time taken from the committed results. They are model-based expectations about on-chain activity, not
price forecasts. How to resolve one: after 2026-12-31 run

    python -m census collect --first 2026-12 --last 2026-12
    python -m census external
    python -m census reproduce && python -m census predictions

The CSV's SHA-256 is in predictions/predictions.csv.sha256, is quoted in the git tag `predictions-frozen`, and is timestamped on Bitcoin with
OpenTimestamps (predictions/predictions.csv.ots; check with `ots verify predictions/predictions.csv.ots`).
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date

from . import config as C

DIR = C.ROOT / "predictions"
CSV = DIR / "predictions.csv"
SHA = DIR / "predictions.csv.sha256"
PERIOD = "2026-12"
RESOLVES_AFTER = "2027-01-01"
FIELDS = ["id", "statement", "quantity", "operator", "threshold", "threshold_high", "unit", "baseline", "baseline_note", "informs", "how_resolved",
          "resolves_after", "frozen_on"]


def _monthly(res: dict, key: str, period: str):
    row = next((r for r in res["monthly"] if r["period"] == period), None)
    return None if row is None else row.get(key)


def _value_row(res: dict, period: str, key: str):
    rows = ((res.get("supply") or {}).get("value") or {}).get("rows") or []
    row = next((r for r in rows if r["period"] == period), None)
    return None if row is None else row.get(key)


def _supply_row(res: dict, period: str, key: str):
    row = next((r for r in (res.get("supply") or {}).get("monthly", []) if r["period"] == period), None)
    return None if row is None else row.get(key)


def _min_version(period: str):
    import pandas as pd
    b = pd.read_csv(C.DERIVED / "sample_blocks.csv.gz", usecols=["period", "protocol_version"])
    b = b[b["period"] == period]
    return None if b.empty else int(b["protocol_version"].min())


def _intents_revenue_sum(period: str):
    """Sum of DefiLlama's daily Intents revenue over a calendar month; None until the snapshot covers every day of it."""
    f = C.ROOT / "data" / "external" / "defillama_near_intents.json"
    if not f.exists():
        return None
    rev = json.loads(f.read_text())["revenue_usd"]
    import calendar
    y, m = map(int, period.split("-"))
    days = [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, calendar.monthrange(y, m)[1] + 1)]
    return sum(rev[d] for d in days) if all(d in rev for d in days) else None


# quantity -> (how to read it from the data, unit)
QUANTITIES = {
    "automated_share_of_transactions": (lambda res: _monthly(res, "tx_auto", PERIOD), "share"),
    "total_activity_tx_per_s": (lambda res: _monthly(res, "total_tx_per_block_ps", PERIOD), "tx/s"),
    "net_issuance_near_per_s": (lambda res: _supply_row(res, PERIOD, "net_issuance_ps"), "NEAR/s"),
    "l1_burn_cover_of_issuance": (lambda res: _supply_row(res, PERIOD, "burn_cover"), "share"),
    "share_of_txs_to_intents_near": (lambda res: _monthly(res, "to_intents", PERIOD), "share"),
    "min_protocol_version_seen": (lambda res: _min_version(PERIOD), "version"),
    "intents_revenue_cover_of_issuance": (lambda res: _value_row(res, PERIOD, "revenue_cover"), "share"),
    "intents_revenue_usd_in_month": (lambda res: _intents_revenue_sum(PERIOD), "USD"),
}


def definitions(res: dict) -> list[dict]:
    """The predictions, with baselines read from the committed results (never typed in)."""
    last = res["monthly"][-1]
    lw = res["latest_window"]["metrics"]
    sw = (res.get("supply") or {}).get("windows") or {}
    vw = ((res.get("supply") or {}).get("value") or {}).get("windows") or {}
    ab = (res.get("windows") or {}).get("abs") or {}
    nov = _intents_revenue_sum("2026-11")
    ext = json.loads((C.ROOT / "data" / "external" / "defillama_near_intents.json").read_text())["revenue_usd"]
    days = sorted(ext)[-31:-1]                       # the last 30 full days in the snapshot
    rev30 = sum(ext[d] for d in days)
    return [
        dict(id="P1", statement="Software-like accounts initiate at least half of sampled NEAR transactions in 2026-12.", quantity="automated_share_of_transactions",
             operator=">=", threshold=0.50, threshold_high="", baseline=last["tx_auto"], baseline_note=f"{last['period']} monthly estimate (95% CI {last['tx_auto_lo']:.2f}-{last['tx_auto_hi']:.2f}); {lw['tx_auto']['point']:.2f} pooled over the latest window",
             informs="C1"),
        dict(id="P2", statement="Total NEAR activity stays below 20 transactions per second in 2026-12 (no return to the 2024-25 regime).", quantity="total_activity_tx_per_s",
             operator="<", threshold=20, threshold_high="", baseline=last["total_tx_per_block_ps"], baseline_note=f"{last['period']} estimate; {ab['total_tx_per_block']['per_s_b']:.1f} tx/s over the latest window against {ab['total_tx_per_block']['per_s_a']:.1f} in 2024-H1" if ab else "",
             informs="C10, C13"),
        dict(id="P3", statement="Net issuance stays between 0.95 and 1.10 NEAR/s in 2026-12 (no new step like 2025-11).", quantity="net_issuance_near_per_s", operator="between",
             threshold=0.95, threshold_high=1.10, baseline=sw["b"]["net_issuance_ps"] if sw else "", baseline_note="latest-window average of the headers' supply slope", informs="C15"),
        dict(id="P4", statement="Estimated L1 fee burn covers less than 2% of gross issuance in 2026-12.", quantity="l1_burn_cover_of_issuance", operator="<", threshold=0.02, threshold_high="",
             baseline=sw["b"]["burn_cover"] if sw else "", baseline_note="latest-window estimate (burn = fee x 0.70 on protocol <= v86, x 1.00 from v87)", informs="C14"),
        dict(id="P5", statement="At least 5% of sampled transactions are addressed to intents.near in 2026-12.", quantity="share_of_txs_to_intents_near", operator=">=", threshold=0.05, threshold_high="",
             baseline=_monthly(res, "to_intents", last["period"]), baseline_note=f"{last['period']} (a partial month); the series is volatile month to month", informs="C4, C12"),
        dict(id="P6", statement="No sampled block in 2026-12 reports a protocol version below 87 (all gas burned).", quantity="min_protocol_version_seen", operator=">=", threshold=87, threshold_high="",
             baseline=_min_version(last["period"]), baseline_note=f"minimum version among the {last['period']} sampled blocks (v87 first appears in that sample)", informs="C14"),
        dict(id="P7", statement="Reported Intents revenue covers at least 10% of gross issuance (USD) in 2026-12.", quantity="intents_revenue_cover_of_issuance", operator=">=", threshold=0.10, threshold_high="",
             baseline=vw["b"]["revenue_cover"] if vw else "", baseline_note="latest-window average; single months ranged widely", informs="C16, C17"),
        dict(id="P8", statement="DefiLlama's reported NEAR Intents revenue for the month of 2026-12 sums to at least $1.2M.", quantity="intents_revenue_usd_in_month", operator=">=", threshold=1_200_000, threshold_high="",
             baseline=rev30, baseline_note=f"the last 30 full days in the snapshot ({days[0]} to {days[-1]})", informs="C16-C18"),
    ]


def freeze() -> None:
    if CSV.exists():
        raise SystemExit(f"{CSV} already exists. Predictions are frozen once; to start a new set, move this directory away deliberately.")
    res = json.loads((C.DERIVED / "results.json").read_text())
    DIR.mkdir(exist_ok=True)
    rows = definitions(res)
    with open(CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            q = QUANTITIES[r["quantity"]]
            w.writerow({**r, "unit": q[1], "baseline": "" if r["baseline"] in ("", None) else f"{float(r['baseline']):.6g}",
                        "how_resolved": "python -m census collect --first 2026-12 --last 2026-12 && python -m census external && python -m census reproduce && python -m census predictions",
                        "resolves_after": RESOLVES_AFTER, "frozen_on": date.today().isoformat()})
    digest = hashlib.sha256(CSV.read_bytes()).hexdigest()
    SHA.write_text(f"{digest}  predictions.csv\n")
    print(f"froze {len(rows)} predictions; sha256 {digest}")


def _holds(op: str, v: float, lo: float, hi: float | None) -> bool:
    return {">=": v >= lo, "<": v < lo, "between": hi is not None and lo <= v <= hi}[op]


def evaluate(row: dict, res: dict):
    """(outcome, value): 'confirmed' / 'refuted' once the data exist, otherwise 'pending'."""
    value = QUANTITIES[row["quantity"]][0](res)
    if value is None:
        return "pending", None
    hi = float(row["threshold_high"]) if row["threshold_high"] not in ("", None) else None
    return ("confirmed" if _holds(row["operator"], float(value), float(row["threshold"]), hi) else "refuted"), float(value)


def run(do_freeze: bool = False) -> None:
    if do_freeze:
        return freeze()
    if not CSV.exists():
        raise SystemExit("No predictions frozen yet. Run: python -m census predictions --freeze")
    recorded = SHA.read_text().split()[0]
    actual = hashlib.sha256(CSV.read_bytes()).hexdigest()
    print(f"predictions.csv sha256 {'MATCHES' if actual == recorded else 'DOES NOT MATCH'} the frozen hash {recorded[:16]}...")
    if actual != recorded:
        raise SystemExit("The file changed after it was frozen; the pre-registration is void.")
    res = json.loads((C.DERIVED / "results.json").read_text())
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    print(f"{'id':3} {'outcome':10} {'rule':22} {'baseline':>10}  statement")
    for r in rows:
        outcome, value = evaluate(r, res)
        rule = f"{r['operator']} {r['threshold']}" + (f"..{r['threshold_high']}" if r["threshold_high"] else "")
        print(f"{r['id']:3} {outcome:10} {rule:22} {r['baseline']:>10}  {r['statement']}" + (f"  [observed {value:.4g}]" if value is not None else ""))


if __name__ == "__main__":
    run("--freeze" in sys.argv)
