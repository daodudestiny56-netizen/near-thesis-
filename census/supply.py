"""Stage 4c - supply: does usage pay for NEAR's issuance?

Everything about the chain side is measured from the same sampled blocks (headers carry `total_supply`, `tokens_burnt` and
`protocol_version`); nothing about inflation is assumed.

  net issuance   slope of total_supply against block time (OLS within a month; R^2 is ~0.9999)
  fees           mean header `tokens_burnt` per block / seconds per block (seconds per block is measured from heights and timestamps)
  burn           fees x 0.70 for blocks on protocol <= v86, x 1.00 from v87. NEAR's gas docs: up to v86 contracts received 30% of the
                 gas they burned (not removed from supply); from v87 all of it is burned.
  gross issuance net issuance + burn   (tokens minted per second)
  coverage       burn / gross issuance

Value capture adds two third-party series from the committed snapshot (census/external.py): NEAR Intents revenue (DefiLlama:
NEAR's net captured revenue; since 2026-02-23 used for open-market buybacks, not burned) and the NEAR price. Those are not measured
here; they are used exactly as published, and the snapshot states its retrieval date.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C
from .analyze import sec_per_block

PRE_V87_BURN_SHARE = 0.70
LAST_PRE_V87 = 86
SECONDS_PER_YEAR = 365.25 * 86400
EXTERNAL = C.ROOT / "data" / "external"


def _month_draws(b: pd.DataFrame, rng: np.random.Generator) -> dict | None:
    """Point estimates and bootstrap draws (over blocks) of per-second net issuance, fees and burn for one month."""
    b = b.sort_values("ts")
    spb = sec_per_block(b)
    if spb is None or len(b) < 5:
        return None
    x = (b["ts"] - b["ts"].min()).to_numpy(float)
    y = (b["total_supply"] - b["total_supply"].min()).to_numpy(float)
    fee = b["tokens_burnt"].to_numpy(float)
    burn = fee * np.where(b["protocol_version"].to_numpy() <= LAST_PRE_V87, PRE_V87_BURN_SHARE, 1.0)
    nb = len(b)
    w = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=C.BOOTSTRAP_RESAMPLES).astype(float)
    sw = w.sum(1)
    xb, yb = (w @ x) / sw, (w @ y) / sw
    var = (w @ (x * x)) / sw - xb ** 2
    net = ((w @ (x * y)) / sw - xb * yb) / np.where(var > 0, var, np.nan)
    fee_ps, burn_ps = (w @ fee) / sw / spb, (w @ burn) / sw / spb
    net0 = float(np.polyfit(x, y, 1)[0])
    return {"spb": spb, "point": {"net": net0, "fee": fee.mean() / spb, "burn": burn.mean() / spb},
            "draws": {"net": net, "fee": fee_ps, "burn": burn_ps}, "v87": bool((b["protocol_version"] > LAST_PRE_V87).any())}


def _ci(a) -> list[float]:
    return [float(v) for v in np.nanpercentile(a, [2.5, 97.5])]


def monthly(blocks: pd.DataFrame) -> tuple[list[dict], dict[str, dict]]:
    rng = np.random.default_rng(C.BOOTSTRAP_SEED + 5)
    rows, keep = [], {}
    for p in sorted(blocks["period"].unique()):
        m = _month_draws(blocks[blocks["period"] == p], rng)
        if not m:
            continue
        d, pt = m["draws"], m["point"]
        gross = d["net"] + d["burn"]
        row = {"period": p, "sec_per_block": m["spb"], "saw_v87": m["v87"],
               "net_issuance_ps": pt["net"], "net_issuance_ps_ci": _ci(d["net"]),
               "fees_ps": pt["fee"], "fees_ps_ci": _ci(d["fee"]),
               "burn_ps": pt["burn"], "burn_ps_ci": _ci(d["burn"]),
               "gross_issuance_ps": pt["net"] + pt["burn"], "gross_issuance_ps_ci": _ci(gross),
               "burn_cover": pt["burn"] / (pt["net"] + pt["burn"]), "burn_cover_ci": _ci(d["burn"] / gross)}
        row["supply_mean"] = float(b_sup := blocks.loc[blocks["period"] == p, "total_supply"].mean())
        row["net_pct_per_year"] = pt["net"] * SECONDS_PER_YEAR / b_sup * 100
        rows.append(row)
        keep[p] = {"net": d["net"], "burn": d["burn"], "fee": d["fee"], "spb": m["spb"]}
    return rows, keep


def _month_no(p: str) -> int:
    return int(p[:4]) * 12 + int(p[5:]) - 1


def largest_step(rows: list[dict], key: str = "net_issuance_ps", ci=lambda r: r["net_issuance_ps_ci"], direction: int = 0) -> dict | None:
    """The change between two CONSECUTIVE sampled months with the largest relative size, and whether their 95% intervals are disjoint.

    Only adjacent calendar months are compared: the sparse baseline months (2022-2023) are not neighbours, so a gap is never read as a step.
    The month pair is chosen from the data, so the interval check is a description of the step, not an independent test of it.
    """
    best = None
    for a, b in zip(rows, rows[1:]):
        if a[key] is None or b[key] is None or a[key] <= 0 or _month_no(b["period"]) - _month_no(a["period"]) != 1:
            continue
        rel = b[key] / a[key] - 1
        if b[key] <= 0 or (direction > 0 and rel <= 0) or (direction < 0 and rel >= 0):
            continue
        size = abs(math.log(b[key] / a[key]))          # symmetric: a fall to 0.2x outranks a rise to 2x
        if best is None or size > best["_size"]:
            ca, cb = ci(a), ci(b)
            best = {"_size": size, "from": a["period"], "to": b["period"], "before": a[key], "after": b[key], "relative_change": rel,
                    "disjoint_intervals": bool(cb[1] < ca[0] or ca[1] < cb[0]),
                    "before_pct_per_year": a.get("net_pct_per_year"), "after_pct_per_year": b.get("net_pct_per_year")}
    if best:
        best.pop("_size")
    return best


def _pool(keep: dict, periods: list[str]) -> dict:
    """Window estimate: equal-weight mean of the months' per-second rates, with the bootstrap draws combined month by month."""
    ps = [p for p in periods if p in keep]
    net = np.mean([keep[p]["net"] for p in ps], axis=0)
    burn = np.mean([keep[p]["burn"] for p in ps], axis=0)
    fee = np.mean([keep[p]["fee"] for p in ps], axis=0)
    return {"periods": ps, "net": net, "burn": burn, "fee": fee, "gross": net + burn}


def windows(rows: list[dict], keep: dict, win: dict | None) -> dict | None:
    if not win:
        return None
    out = {}
    for tag in ("a", "b"):
        w = _pool(keep, win[tag])
        pts = {k: float(np.mean([r[k] for r in rows if r["period"] in w["periods"]])) for k in ("net_issuance_ps", "burn_ps", "fees_ps")}
        gross = pts["net_issuance_ps"] + pts["burn_ps"]
        out[tag] = {"periods": w["periods"], "net_issuance_ps": pts["net_issuance_ps"], "net_issuance_ps_ci": _ci(w["net"]),
                    "burn_ps": pts["burn_ps"], "burn_ps_ci": _ci(w["burn"]), "fees_ps": pts["fees_ps"], "fees_ps_ci": _ci(w["fee"]),
                    "gross_issuance_ps": gross, "gross_issuance_ps_ci": _ci(w["gross"]),
                    "burn_cover": pts["burn_ps"] / gross, "burn_cover_ci": _ci(w["burn"] / w["gross"])}
    return out


# ------------------------------------------------------------------------------------------------ value capture (USD)

def _load_external() -> tuple[dict, dict, dict] | None:
    f, p = EXTERNAL / "defillama_near_intents.json", EXTERNAL / "defillama_near_price.json"
    if not (f.exists() and p.exists()):
        return None
    snap = json.loads(f.read_text())
    return snap, json.loads(p.read_text())["usd"], snap["methodology"]


def value_capture(rows: list[dict], keep: dict, win: dict | None) -> dict | None:
    ext = _load_external()
    if not ext:
        return None
    snap, price, method = ext
    last_full = (date.fromisoformat(max(snap["fees_usd"])) - timedelta(days=1)).isoformat()   # the newest day is partial
    days = sorted(d for d in snap["fees_usd"] if d <= last_full)
    by_month: dict[str, list[str]] = {}
    for d in days:
        by_month.setdefault(d[:7], []).append(d)
    first_month = days[0][:7]
    out_rows = []
    for r in rows:
        p = r["period"]
        ds = by_month.get(p)
        if not ds or p == first_month:                       # the first month is a partial month of Intents data
            continue
        px = float(np.mean([price[d] for d in ds if d in price]))
        rev = float(np.mean([snap["revenue_usd"][d] for d in ds]))
        fees = float(np.mean([snap["fees_usd"][d] for d in ds]))
        k = keep[p]
        iss_usd = (k["net"] + k["burn"]) * 86400 * px
        out_rows.append({
            "period": p, "days": len(ds), "near_price_usd": px, "intents_revenue_usd_day": rev, "intents_fees_usd_day": fees,
            "issuance_usd_day": float(np.mean(iss_usd)), "issuance_usd_day_ci": _ci(iss_usd),
            "l1_fees_usd_day": r["fees_ps"] * 86400 * px, "l1_burn_usd_day": r["burn_ps"] * 86400 * px,
            "revenue_cover": rev / float(np.mean(iss_usd)), "revenue_cover_ci": _ci(rev / iss_usd),
            "burn_cover": r["burn_cover"]})
    res = {"rows": out_rows, "snapshot_retrieved_on": snap["retrieved_on"], "last_full_day": last_full, "first_day": days[0],
           "methodology": method, "windows": None}
    if win and out_rows:
        have = {r["period"]: r for r in out_rows}
        va = [p for p in win["b"] if p in have]
        # first-vs-latest for the Intents era: the first six full months with data against the latest window
        first6 = [r["period"] for r in out_rows][:6]
        wins = {}
        for tag, ps in (("a", first6), ("b", va)):
            ps = [p for p in ps if p in have]
            if not ps:
                continue
            iss = np.mean([(keep[p]["net"] + keep[p]["burn"]) * 86400 * have[p]["near_price_usd"] for p in ps], axis=0)
            rev = float(np.mean([have[p]["intents_revenue_usd_day"] for p in ps]))
            l1 = float(np.mean([have[p]["l1_fees_usd_day"] for p in ps]))
            burn_usd = np.mean([keep[p]["burn"] * 86400 * have[p]["near_price_usd"] for p in ps], axis=0)
            wins[tag] = {"periods": ps, "near_price_usd": float(np.mean([have[p]["near_price_usd"] for p in ps])), "intents_revenue_usd_day": rev, "intents_fees_usd_day": float(np.mean([have[p]["intents_fees_usd_day"] for p in ps])),
                         "l1_fees_usd_day": l1, "issuance_usd_day": float(np.mean(iss)), "issuance_usd_day_ci": _ci(iss),
                         "revenue_cover": rev / float(np.mean(iss)), "revenue_cover_ci": _ci(rev / iss),
                         "revenue_vs_l1_fees": rev / l1 if l1 else None,
                         "burn_usd_day": float(np.mean(burn_usd)), "burn_cover_usd": float(np.mean(burn_usd) / np.mean(iss)),
                         "burn_cover_usd_ci": _ci(burn_usd / iss),
                         "combined_cover": (rev + float(np.mean(burn_usd))) / float(np.mean(iss)),
                         "combined_cover_ci": _ci((rev + burn_usd) / iss)}
        res["windows"] = wins
    return res


def run_analysis(blocks: pd.DataFrame, win: dict | None) -> dict:
    rows, keep = monthly(blocks)
    return {"monthly": rows, "windows": windows(rows, keep, win), "value": value_capture(rows, keep, win),
            "issuance_step": largest_step(rows),
            "assumptions": {"pre_v87_burn_share": PRE_V87_BURN_SHARE, "last_pre_v87_version": LAST_PRE_V87,
                            "first_month_with_v87": next((r["period"] for r in rows if r["saw_v87"]), None)}}
