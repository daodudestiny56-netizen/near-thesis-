"""Stage 4 - analyze: monthly automated share, fee payers, concentration and a trend extrapolation.

Estimator. Blocks are drawn uniformly at random within each month, so a ratio such as
    automated txs / all txs
is estimated as  sum(automated txs over sampled blocks) / sum(all txs over sampled blocks).
Transactions within a block are not independent, so confidence intervals come from a *cluster
bootstrap over blocks* (resample whole blocks, B times, recompute the ratio).

Only transaction- and fee-weighted shares are reported. A share of *distinct accounts* would be
biased towards bots (a bot is in nearly every sampled block; a once-a-week human almost never is),
so account-level questions are answered with concentration statistics instead.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from . import config as C
from .util import jsonable

AUTO, HUMAN, LOW = "automated", "human", "low_activity"


def _bootstrap(num: np.ndarray, den: np.ndarray, rng: np.random.Generator):
    """Ratio estimate, 95% CI and the raw bootstrap draws for per-block numerators/denominators."""
    nb = len(num)
    if nb == 0 or den.sum() == 0:
        return None
    point = float(num.sum() / den.sum())
    w = rng.multinomial(nb, np.full(nb, 1.0 / nb), size=C.BOOTSTRAP_RESAMPLES).astype(float)
    d = w @ den
    draws = np.where(d > 0, (w @ num) / np.where(d > 0, d, 1), np.nan)
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return point, float(lo), float(hi), draws


def _block_table(txs: pd.DataFrame, blocks: pd.DataFrame, mask: pd.Series | None, weight: str | None) -> pd.DataFrame:
    """Per-block sum of (1 or fee) over rows where mask is true, aligned to every sampled block."""
    sub = txs if mask is None else txs[mask]
    vals = sub[weight] if weight else pd.Series(1.0, index=sub.index)
    s = vals.groupby([sub["period"], sub["height"]]).sum()
    idx = pd.MultiIndex.from_frame(blocks[["period", "height"]])
    return s.reindex(idx, fill_value=0.0).to_numpy()


def monthly_series(txs: pd.DataFrame, blocks: pd.DataFrame) -> tuple[list[dict], dict[str, np.ndarray]]:
    rng = np.random.default_rng(C.BOOTSTRAP_SEED)
    rows, headline_draws = [], {}
    periods = sorted(blocks["period"].unique())
    txs = txs.copy()
    for col in ("relayed", "success"):
        txs[col] = txs[col].astype(bool)
    txs["to_intents"] = txs["real_receiver"].eq(C.INTENTS_CONTRACT) | txs["receiver"].eq(C.INTENTS_CONTRACT)

    specs = {   # name -> (numerator mask, weight column, denominator mask)
        "tx_auto": (txs["init_class"].eq(AUTO), None, None),
        "tx_auto_upper": (txs["init_class"].isin([AUTO, LOW]), None, None),
        "tx_human": (txs["init_class"].eq(HUMAN), None, None),
        "tx_low": (txs["init_class"].eq(LOW), None, None),
        "tx_auto_of_classified": (txs["init_class"].eq(AUTO), None, txs["init_class"].isin([AUTO, HUMAN])),
        "fee_init_auto": (txs["init_class"].eq(AUTO), "fee_near", None),
        "fee_init_auto_upper": (txs["init_class"].isin([AUTO, LOW]), "fee_near", None),
        "fee_paid_auto": (txs["payer_class"].eq(AUTO), "fee_near", None),
        "relayed": (txs["relayed"], None, None),
        "to_intents": (txs["to_intents"], None, None),
        "failed": (~txs["success"], None, None),
    }
    for p in periods:
        b = blocks[blocks["period"] == p].reset_index(drop=True)
        t = txs[txs["period"] == p]
        row = {"period": p, "blocks": int(len(b)), "txs_sampled": int(len(t)),
               "tx_per_block": float(b["num_tx"].mean()), "fee_near_per_block": float(b["tokens_burnt"].mean())}
        for name, (nmask, weight, dmask) in specs.items():
            num = _block_table(t, b, nmask.loc[t.index], weight)
            den = _block_table(t, b, None if dmask is None else dmask.loc[t.index], weight)
            res = _bootstrap(num, den, rng)
            if res is None:
                continue
            point, lo, hi, draws = res
            row[name], row[name + "_lo"], row[name + "_hi"] = point, lo, hi
            if name == "tx_auto":
                headline_draws[p] = draws
        rows.append(row)
    return rows, headline_draws


def trend_forecast(periods: list[str], draws: dict[str, np.ndarray], months: int = 24, horizon: int = 12) -> dict:
    """Extrapolate the logit of the automated share with an OLS line, propagating measurement error.

    Each bootstrap replicate b takes the b-th resampled share of every month, fits a line to
    logit(share) over the last `months` months and projects `horizon` months ahead. The 2.5-97.5
    band therefore reflects *sampling* uncertainty only; it does not include model risk or regime change.
    """
    use = [p for p in periods if p in draws][-months:]
    if len(use) < 6:
        return {}
    x = np.arange(len(use), dtype=float)
    mat = np.clip(np.vstack([draws[p] for p in use]), 0.001, 0.999)       # months x B
    logit = np.log(mat / (1 - mat))
    xm = x - x.mean()
    slope = (xm[:, None] * (logit - logit.mean(axis=0))).sum(axis=0) / (xm ** 2).sum()
    inter = logit.mean(axis=0) - slope * x.mean()
    fx = np.arange(len(use), len(use) + horizon, dtype=float)
    proj = 1 / (1 + np.exp(-(inter[None, :] + slope[None, :] * fx[:, None])))       # horizon x B
    last = pd.Period(use[-1], "M")
    labels = [str(last + i + 1) for i in range(horizon)]
    return {
        "fit_months": use, "horizon": labels,
        "slope_logit_per_month_median": float(np.median(slope)),
        "slope_logit_per_month_ci": [float(v) for v in np.percentile(slope, [2.5, 97.5])],
        "share_p50": [float(v) for v in np.percentile(proj, 50, axis=1)],
        "share_lo": [float(v) for v in np.percentile(proj, 2.5, axis=1)],
        "share_hi": [float(v) for v in np.percentile(proj, 97.5, axis=1)],
        "prob_slope_positive": float((slope > 0).mean()),
    }


def concentration(txs: pd.DataFrame, last_n_periods: int = 6, top: int = 15) -> dict:
    periods = sorted(txs["period"].unique())[-last_n_periods:]
    t = txs[txs["period"].isin(periods)]
    auto = t[t["init_class"] == AUTO]
    n_all, fee_all = len(t), t["fee_near"].sum()
    by = (auto.groupby("real_signer")
          .agg(txs=("hash", "size"), fee=("fee_near", "sum"), top_receiver=("real_receiver", lambda s: s.value_counts().index[0]),
               relayed=("relayed", "mean"))
          .sort_values("txs", ascending=False))
    by["tx_share"] = by["txs"] / n_all
    by["fee_share"] = by["fee"] / fee_all
    cum = by["txs"].cumsum() / by["txs"].sum() if len(by) else pd.Series(dtype=float)
    n50 = int((cum < 0.5).sum() + 1) if len(by) else 0
    return {
        "periods": periods, "automated_accounts_in_sample": int(len(by)),
        "accounts_for_half_of_automated_txs": n50,
        "top_automated": [{"account": a, "tx_share": float(r.tx_share), "fee_share": float(r.fee_share),
                           "top_receiver": r.top_receiver, "relayed": float(r.relayed)}
                          for a, r in by.head(top).iterrows()],
    }


def run() -> None:
    txs = pd.read_csv(C.DERIVED / "classified_txs.csv.gz", low_memory=False)
    blocks = pd.read_csv(C.DERIVED / "sample_blocks.csv.gz")
    rows, draws = monthly_series(txs, blocks)
    periods = [r["period"] for r in rows]
    res = {
        "generated_from": {"months": len(periods), "blocks": int(len(blocks)), "txs": int(len(txs)),
                           "first": periods[0], "last": periods[-1]},
        "monthly": rows,
        "forecast": trend_forecast(periods, draws),
        "concentration": concentration(txs),
    }
    (C.DERIVED / "results.json").write_text(json.dumps(jsonable(res), indent=1))
    last = rows[-1]
    print(f"{len(rows)} months. latest {last['period']}: automated tx share "
          f"{last['tx_auto']:.1%} [{last['tx_auto_lo']:.1%}, {last['tx_auto_hi']:.1%}] "
          f"(upper bound {last['tx_auto_upper']:.1%})")


if __name__ == "__main__":
    run()
