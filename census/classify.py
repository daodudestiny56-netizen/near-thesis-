"""Stage 2 - classify: turn behavioural features into an automation score and a class.

The classifier is a transparent additive rule list, not a fitted model: every rule is a named
condition with a point value, so any verdict can be explained rule by rule and the validation
step can ablate rules one at a time. Account names, NEAR Social profiles and every other
off-chain signal are deliberately *not* inputs; they are used only to build independent labels.

Classes
  automated     score >= AUTOMATED_THRESHOLD  (software-driven: bots, keepers, relayers, agents)
  human         score <  AUTOMATED_THRESHOLD and enough history to judge
  low_activity  fewer than MIN_OBS signed transactions observed - not enough evidence either way

"Automated" is a behavioural class. It includes classic bots and infrastructure as well as AI agents;
behaviour alone cannot separate those. METHODOLOGY.md discusses this limit.
"""
from __future__ import annotations

import gzip
import math
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from . import config as C


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


@dataclass(frozen=True)
class Rule:
    name: str
    points: int
    test: Callable[[dict], bool]
    why: str


def _ge(key, v):
    return lambda f: _ok(f.get(key)) and f[key] >= v


def _lt(key, v):
    return lambda f: _ok(f.get(key)) and f[key] < v


RULES: list[Rule] = [
    # volume -- machines sign far more transactions than people do
    Rule("lifetime_volume_very_high", 20, _ge("txs_count_total", 20_000), ">= 20k signed txs"),
    Rule("lifetime_volume_high", 10, lambda f: _ok(f.get("txs_count_total")) and 2_000 <= f["txs_count_total"] < 20_000, "2k-20k signed txs"),
    Rule("sustained_rate_very_high", 15, _ge("rate_per_day", 500), ">= 500 txs/day in window"),
    Rule("sustained_rate_high", 8, lambda f: _ok(f.get("rate_per_day")) and 100 <= f["rate_per_day"] < 500, "100-500 txs/day in window"),
    # timing -- machine speed and schedules
    Rule("machine_speed_gaps", 20, _ge("fast_share", 0.5), ">= 50% of gaps <= 5 s"),
    Rule("frequent_machine_speed_gaps", 10, lambda f: _ok(f.get("fast_share")) and 0.2 <= f["fast_share"] < 0.5, "20-50% of gaps <= 5 s"),
    Rule("on_a_schedule", 20, _ge("periodic_share", 0.5), ">= 50% of gaps within +-10% of the median gap"),
    Rule("partly_on_a_schedule", 10, lambda f: _ok(f.get("periodic_share")) and 0.25 <= f["periodic_share"] < 0.5, "25-50% on schedule"),
    # circadian -- humans sleep
    Rule("never_rests_around_the_clock", 20, lambda f: _ok(f.get("rest_per_day")) and f["rest_per_day"] < 0.2 and _ok(f.get("hour_coverage")) and f["hour_coverage"] >= 0.9, "active in >=90% of UTC hours, almost no 5h silences"),
    # call shape
    Rule("function_call_key_shape", 5, _ge("fc_key_share", 0.8), "most sampled txs are single zero-deposit FunctionCalls (function-call-key shape)"),
    Rule("high_failure_rate", 5, _ge("fail_rate", 0.3), ">= 30% of txs fail (retrying scripts)"),
    # evidence of a human
    Rule("sleeps_every_day", -20, _ge("rest_per_day", 0.8), "a >=5 h silence nearly every day"),
    Rule("low_activity_rate", -10, lambda f: _ok(f.get("rate_per_day")) and f["rate_per_day"] < 5, "< 5 txs/day"),
    Rule("daytime_only_hours", -10, lambda f: _ok(f.get("hour_coverage")) and f["hour_coverage"] < 0.6, "active in < 60% of UTC hours"),
]
RULE_NAMES = [r.name for r in RULES]


def score(f: dict, skip: set[str] | None = None) -> tuple[int, list[str]]:
    skip = skip or set()
    total, fired = 0, []
    for r in RULES:
        if r.name in skip:
            continue
        if r.test(f):
            total += r.points
            fired.append(r.name)
    return max(0, min(100, total)), fired


def label_of(f: dict, s: int) -> str:
    if (f.get("n_obs") or 0) < C.MIN_OBS:
        return "low_activity"
    return "automated" if s >= C.AUTOMATED_THRESHOLD else "human"


def classify_frame(feats: pd.DataFrame, skip: set[str] | None = None) -> pd.DataFrame:
    scores, classes, fired = [], [], []
    for rec in feats.to_dict("records"):
        s, why = score(rec, skip)
        scores.append(s)
        classes.append(label_of(rec, s))
        fired.append("|".join(why))
    out = feats.copy()
    out["score"], out["klass"], out["fired"] = scores, classes, fired
    return out


def run() -> None:
    txs = pd.read_csv(C.DERIVED / "sample_txs.csv.gz", low_memory=False)
    acc = pd.read_csv(C.DERIVED / "account_features.csv.gz", low_memory=False)

    # account-level call-shape evidence from the sampled full transactions
    shaped = txs[txs["kind"].notna()].copy()
    shaped["fc"] = shaped["fc_key_consistent"].astype(str).eq("True")
    shaped["intents"] = shaped["touches_intents"].astype(str).eq("True")
    agg = (shaped.groupby(["period", "real_signer"])
           .agg(fc_key_share=("fc", "mean"), intents_share=("intents", "mean"), n_shaped=("fc", "size"))
           .reset_index().rename(columns={"real_signer": "account"}))
    agg["role"] = "real"
    acc = acc.merge(agg, on=["period", "account", "role"], how="left")

    acc = classify_frame(acc)
    out = C.DERIVED / "account_classes.csv.gz"
    with gzip.open(out, "wt", newline="") as fh:
        acc.to_csv(fh, index=False)

    key = acc.set_index(["period", "account", "role"])["klass"]
    sc = acc.set_index(["period", "account", "role"])["score"]
    real = [(p, a, "real") for p, a in zip(txs["period"], txs["real_signer"])]
    txs["init_class"] = [key.get(k, "low_activity") for k in real]
    txs["init_score"] = [sc.get(k, 0) for k in real]
    paid = [(p, a, "real" if a == r else "top") for p, a, r in zip(txs["period"], txs["payer"], txs["real_signer"])]
    txs["payer_class"] = [key.get(k, "low_activity") for k in paid]
    out2 = C.DERIVED / "classified_txs.csv.gz"
    with gzip.open(out2, "wt", newline="") as fh:
        txs.to_csv(fh, index=False)
    print(f"classified {len(acc):,} account-periods and {len(txs):,} sampled transactions")
    print(txs["init_class"].value_counts(normalize=True).round(3).to_string())
