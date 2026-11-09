"""Stage 4b - insights: extra evidence computed from the same sample (nothing here is typed by hand).

  hourly        UTC hour-of-day profile of automated vs human-like transactions (a behavioural fingerprint)
  receivers     what automated and human-like accounts actually call
  methods       most common methods among the fully fetched transactions (a subsample, unweighted)
  fee_stats     fee per transaction by class
  windows       first-vs-latest window tests with bootstrap intervals (is it rising?)
  accounts      per-account verdicts with the rules that fired (powers the dashboard's lookup box)
  spot_check    a seeded random sample of transactions with explorer links, so anyone can verify by hand
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import config as C
from .analyze import AUTO, HUMAN, LOW, _block_table, make_specs

EXPLORER = "https://nearblocks.io/txns/"
WINDOW_METRICS = ("tx_auto", "fee_init_auto", "fee_paid_auto", "relayed", "to_intents")
LATEST_METRICS = WINDOW_METRICS + ("tx_auto_upper", "tx_auto_t40", "tx_auto_t60", "tx_low", "fee_init_auto_upper")


def recent_periods(periods: list[str], n: int = 6) -> list[str]:
    return sorted(periods)[-n:]


def _busiest_6h(hours: np.ndarray) -> float:
    c = np.bincount(hours, minlength=24) / max(len(hours), 1)
    return float(max(sum(c[(h + k) % 24] for k in range(6)) for h in range(24)))


def hourly(txs: pd.DataFrame, periods: list[str]) -> dict:
    """UTC hour-of-day profile per class, plus a bootstrap test of which class has the stronger daily rhythm.

    Rhythm = share of a class's transactions falling in its busiest 6 consecutive hours (25% if perfectly flat).
    The verdict is decided from the 95% interval of (human-like minus automated), so a null result is reported as such.
    """
    t = txs[txs["period"].isin(periods)].copy()
    t["hour"] = ((t["ts"] // 3600) % 24).astype(int)
    out = {"periods": periods}
    hrs = {}
    for name, klass in (("automated", AUTO), ("human", HUMAN)):
        h = t.loc[t["init_class"] == klass, "hour"].to_numpy()
        hrs[name] = h
        c = np.bincount(h, minlength=24)
        n = int(c.sum())
        share = (c / n).tolist() if n else [0.0] * 24
        out[name] = {"n": n, "share": share,
                     "peak_to_trough": (max(share) / min(share)) if n and min(share) > 0 else None,
                     "busiest_6h_share": _busiest_6h(h) if n else None,
                     "hours_with_activity": int((c > 0).sum())}
    verdict, diff = "not_testable", None
    if len(hrs["automated"]) >= 50 and len(hrs["human"]) >= 50:
        rng = np.random.default_rng(C.BOOTSTRAP_SEED + 3)
        draws = [_busiest_6h(rng.choice(hrs["human"], len(hrs["human"]))) - _busiest_6h(rng.choice(hrs["automated"], len(hrs["automated"])))
                 for _ in range(500)]
        lo, hi = np.percentile(draws, [2.5, 97.5])
        point = out["human"]["busiest_6h_share"] - out["automated"]["busiest_6h_share"]
        diff = {"point": float(point), "lo": float(lo), "hi": float(hi)}
        verdict = "human_more_rhythmic" if lo > 0 else "automated_more_rhythmic" if hi < 0 else "no_clear_difference"
    out["rhythm_verdict"], out["rhythm_diff"] = verdict, diff
    return out


def receivers(txs: pd.DataFrame, periods: list[str], top: int = 12) -> dict:
    t = txs[txs["period"].isin(periods)]
    out = {"periods": periods}
    for name, klass in (("automated", AUTO), ("human", HUMAN)):
        k = t[t["init_class"] == klass]
        if not len(k):
            out[name] = []
            continue
        g = k.groupby("real_receiver").agg(txs=("hash", "size"), fee=("fee_near", "sum")).sort_values("txs", ascending=False)
        out[name] = [{"receiver": r, "tx_share": float(v.txs / len(k)), "fee_share": float(v.fee / k["fee_near"].sum())}
                     for r, v in g.head(top).iterrows()]
        out[name + "_n"] = int(len(k))
    return out


def methods(txs: pd.DataFrame, periods: list[str], top: int = 10) -> dict:
    t = txs[txs["period"].isin(periods) & txs["method"].notna()]
    out = {"periods": periods, "note": "fully fetched subsample (up to 3 txs per signer per month); unweighted"}
    for name, klass in (("automated", AUTO), ("human", HUMAN)):
        k = t[t["init_class"] == klass]
        vc = k["method"].value_counts()
        out[name] = [{"method": m, "share": float(c / len(k))} for m, c in vc.head(top).items()] if len(k) else []
        out[name + "_n"] = int(len(k))
    return out


def fee_stats(txs: pd.DataFrame, periods: list[str]) -> dict:
    t = txs[txs["period"].isin(periods)]
    out = {"periods": periods}
    for name, klass in (("automated", AUTO), ("human", HUMAN)):
        f = t.loc[t["init_class"] == klass, "fee_near"]
        out[name] = {"n": int(len(f)), "median_near": float(f.median()) if len(f) else None,
                     "mean_near": float(f.mean()) if len(f) else None}
    a, h = out["automated"], out["human"]
    out["mean_ratio_auto_over_human"] = (a["mean_near"] / h["mean_near"]) if a["mean_near"] and h["mean_near"] else None
    return out


def _pool(txs, blocks, specs, name, periods):
    nmask, weight, dmask = specs[name]
    nums, dens = [], []
    for p in periods:
        b = blocks[blocks["period"] == p].reset_index(drop=True)
        t = txs[txs["period"] == p]
        nums.append(_block_table(t, b, nmask.loc[t.index], weight))
        dens.append(_block_table(t, b, None if dmask is None else dmask.loc[t.index], weight))
    return np.concatenate(nums), np.concatenate(dens)


def latest_window(txs: pd.DataFrame, blocks: pd.DataFrame, periods: list[str], size: int = 6) -> dict:
    """Pooled estimate and 95% cluster-bootstrap CI over the last `size` sampled periods."""
    ps = sorted(periods)[-size:]
    specs = make_specs(txs)
    rng = np.random.default_rng(C.BOOTSTRAP_SEED + 2)
    out = {"periods": ps, "metrics": {}}
    for name in LATEST_METRICS:
        num, den = _pool(txs, blocks, specs, name, ps)
        if den.sum() == 0:
            continue
        nb = len(num)
        w = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=C.BOOTSTRAP_RESAMPLES).astype(float)
        d = w @ den
        draws = np.where(d > 0, (w @ num) / np.where(d > 0, d, 1), np.nan)
        lo, hi = np.nanpercentile(draws, [2.5, 97.5])
        out["metrics"][name] = {"point": float(num.sum() / den.sum()), "lo": float(lo), "hi": float(hi)}
    return out


def windows(txs: pd.DataFrame, blocks: pd.DataFrame, periods: list[str], size: int = 6) -> dict | None:
    """Pool the first `size` periods from DENSE_FROM and the last `size` periods; bootstrap the difference."""
    dense = [p for p in sorted(periods) if p >= C.DENSE_FROM]
    if len(dense) < 2 * size:
        return None
    a_p, b_p = dense[:size], dense[-size:]
    specs = make_specs(txs)
    rng = np.random.default_rng(C.BOOTSTRAP_SEED + 1)
    out = {"a": a_p, "b": b_p, "metrics": {}}
    for name in WINDOW_METRICS:
        nmask, weight, dmask = specs[name]
        pooled = {}
        for tag, ps in (("a", a_p), ("b", b_p)):
            nums, dens = [], []
            for p in ps:
                b = blocks[blocks["period"] == p].reset_index(drop=True)
                t = txs[txs["period"] == p]
                nums.append(_block_table(t, b, nmask.loc[t.index], weight))
                dens.append(_block_table(t, b, None if dmask is None else dmask.loc[t.index], weight))
            pooled[tag] = (np.concatenate(nums), np.concatenate(dens))
        draws = {}
        for tag, (num, den) in pooled.items():
            nb = len(num)
            w = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=C.BOOTSTRAP_RESAMPLES).astype(float)
            d = w @ den
            draws[tag] = np.where(d > 0, (w @ num) / np.where(d > 0, d, 1), np.nan)
        diff = draws["b"] - draws["a"]
        pa, pb = pooled["a"][0].sum() / pooled["a"][1].sum(), pooled["b"][0].sum() / pooled["b"][1].sum()
        lo, hi = np.nanpercentile(diff, [2.5, 97.5])
        out["metrics"][name] = {"a": float(pa), "b": float(pb), "diff": float(pb - pa), "diff_lo": float(lo), "diff_hi": float(hi),
                                "a_ci": [float(v) for v in np.nanpercentile(draws["a"], [2.5, 97.5])],
                                "b_ci": [float(v) for v in np.nanpercentile(draws["b"], [2.5, 97.5])]}
    return out


def accounts(txs: pd.DataFrame, acc: pd.DataFrame, periods: list[str], n_auto: int = 60, n_human: int = 40) -> dict:
    t = txs[txs["period"].isin(periods)]
    a = acc[(acc["role"] == "real") & acc["period"].isin(periods)].sort_values("period").groupby("account").tail(1)
    counts = t.groupby("real_signer").agg(sample_txs=("hash", "size"), top_receiver=("real_receiver", lambda s: s.value_counts().index[0]),
                                          fee=("fee_near", "sum"))
    a = a.merge(counts, left_on="account", right_index=True, how="inner")
    keep = []
    for klass, n in ((AUTO, n_auto), (HUMAN, n_human)):
        keep.append(a[a["klass"] == klass].sort_values("sample_txs", ascending=False).head(n))
    a = pd.concat(keep)
    cols = ["n_obs", "txs_count_total", "rate_per_day", "gap_median_s", "fast_share", "periodic_share", "rest_per_day",
            "hour_coverage", "fail_rate", "span_days"]
    res = {}
    for r in a.to_dict("records"):
        res[r["account"]] = {"klass": r["klass"], "score": int(r["score"]), "fired": [x for x in str(r["fired"]).split("|") if x and x != "nan"],
                             "sample_txs": int(r["sample_txs"]), "top_receiver": r["top_receiver"], "period": r["period"],
                             **{c: (None if pd.isna(r[c]) else float(r[c])) for c in cols}}
    return res


def spot_check(txs: pd.DataFrame, acc: pd.DataFrame, periods: list[str], n: int = 30) -> list[dict]:
    t = txs[txs["period"].isin(periods)]
    t = t.sample(min(n, len(t)), random_state=C.SEED).sort_values("ts", ascending=False)
    fired = acc[acc["role"] == "real"].set_index(["period", "account"])["fired"].to_dict()
    out = []
    for r in t.to_dict("records"):
        f = fired.get((r["period"], r["real_signer"]), "")
        out.append({
            "hash": r["hash"], "url": EXPLORER + r["hash"], "period": r["period"],
            "time_utc": datetime.fromtimestamp(int(r["ts"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "initiator": r["real_signer"], "payer": r["payer"], "receiver": r["real_receiver"],
            "klass": r["init_class"], "score": int(r["init_score"]), "relayed": bool(r["relayed"]),
            "fee_near": float(r["fee_near"]), "fired": [x for x in str(f).split("|") if x and x != "nan"],
        })
    return out
