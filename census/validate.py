"""Stage 3 - validate: measure the classifier against the hand-built labelled set.

Labels (data/labels/labels.csv) come from evidence the classifier never sees - account naming,
NEAR Social profiles, documented infrastructure roles - see labels.py and METHODOLOGY.md.
Half the labels (chosen by a hash of the account id, so nobody can cherry-pick) are a held-out
TEST split. Rule weights were set on the DEV split only; the headline accuracy is TEST only.

Reported: coverage (the classifier may abstain as "low_activity"), per-class precision/recall with
Wilson 95% intervals, balanced accuracy, ROC AUC of the raw score, a leave-one-rule-out ablation,
and a Rogan-Gladen correction that converts the measured error rates into a bias-adjusted share.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pandas as pd

from . import config as C
from .util import jsonable
from .classify import RULE_NAMES, classify_frame


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def split_of(account: str) -> str:
    return "test" if int(hashlib.sha1(account.encode()).hexdigest(), 16) % 2 else "dev"


def auc(scores: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney U form of ROC AUC (ties count half)."""
    pos, neg = scores[y == 1], scores[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _confusion(df: pd.DataFrame) -> dict:
    """df has `label` (truth) and `klass` (prediction) in {automated, human, low_activity}."""
    classified = df[df["klass"] != "low_activity"]
    tp = int(((classified["label"] == "automated") & (classified["klass"] == "automated")).sum())
    fn = int(((classified["label"] == "automated") & (classified["klass"] == "human")).sum())
    tn = int(((classified["label"] == "human") & (classified["klass"] == "human")).sum())
    fp = int(((classified["label"] == "human") & (classified["klass"] == "automated")).sum())
    tpr = tp / (tp + fn) if tp + fn else float("nan")
    tnr = tn / (tn + fp) if tn + fp else float("nan")
    prec = tp / (tp + fp) if tp + fp else float("nan")
    return {
        "n_labelled": int(len(df)), "n_classified": int(len(classified)),
        "coverage": len(classified) / len(df) if len(df) else float("nan"),
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "recall_automated": tpr, "recall_automated_ci": wilson(tp, tp + fn),
        "recall_human": tnr, "recall_human_ci": wilson(tn, tn + fp),
        "precision_automated": prec, "precision_automated_ci": wilson(tp, tp + fp),
        "balanced_accuracy": (tpr + tnr) / 2 if not (math.isnan(tpr) or math.isnan(tnr)) else float("nan"),
        "accuracy": (tp + tn) / len(classified) if len(classified) else float("nan"),
        "accuracy_ci": wilson(tp + tn, len(classified)),
    }


def rogan_gladen(observed: float, tpr: float, fpr: float) -> float | None:
    """True prevalence from an observed positive rate, given sensitivity and false-positive rate."""
    denom = tpr - fpr
    if denom <= 0.05:
        return None
    return float(min(1.0, max(0.0, (observed - fpr) / denom)))


def run() -> None:
    labels = pd.read_csv(C.LABELS / "labels.csv")
    labels = labels[labels["label"].isin(["automated", "human"])].copy()
    labels["split"] = labels["account"].map(split_of)
    acc = pd.read_csv(C.DERIVED / "account_classes.csv.gz", low_memory=False)
    acc = acc[acc["role"] == "real"]
    # one observation per labelled account: the most recent month it was profiled with any history
    acc = acc.sort_values(["account", "period"]).groupby("account").tail(1)
    extra_path = C.LABELS / "label_features.csv"          # label accounts that are not in the transaction sample
    if extra_path.exists():
        extra = classify_frame(pd.read_csv(extra_path))
        acc = pd.concat([acc, extra[~extra["account"].isin(acc["account"])]], ignore_index=True)
    df = labels.merge(acc, on="account", how="inner")
    print(f"{len(labels)} labels, {len(df)} found in the collected sample")

    out: dict = {"n_labels": int(len(labels)), "n_matched": int(len(df)),
                 "label_sources": labels["evidence_type"].value_counts().to_dict()}
    for name, part in (("dev", df[df["split"] == "dev"]), ("test", df[df["split"] == "test"]), ("all", df)):
        out[name] = _confusion(part)

    test = df[df["split"] == "test"]
    scored = test[test["klass"] != "low_activity"]
    out["test"]["auc"] = auc(scored["score"].to_numpy(float), (scored["label"] == "automated").to_numpy(int))

    # leave-one-rule-out ablation on TEST (re-scores from the raw features)
    feats = test.drop(columns=["score", "klass", "fired"])
    ablation = {"all_rules": out["test"]["balanced_accuracy"]}
    for rule in RULE_NAMES:
        r = classify_frame(feats, skip={rule})
        r["label"] = test["label"].to_numpy()
        ablation[f"without:{rule}"] = _confusion(r)["balanced_accuracy"]
    out["ablation_test_balanced_accuracy"] = ablation

    # threshold sweep (TEST), to show the chosen threshold is not on a knife edge
    sweep = []
    for thr in range(30, 75, 5):
        r = test.copy()
        r["klass"] = np.where(r["klass"] == "low_activity", "low_activity",
                              np.where(r["score"] >= thr, "automated", "human"))
        c = _confusion(r)
        sweep.append({"threshold": thr, "balanced_accuracy": c["balanced_accuracy"],
                      "recall_automated": c["recall_automated"], "recall_human": c["recall_human"]})
    out["threshold_sweep_test"] = sweep

    # bias adjustment inputs, from TEST rates
    t = out["test"]
    fpr = 1 - t["recall_human"] if not math.isnan(t["recall_human"]) else float("nan")
    out["rates_for_correction"] = {"tpr": t["recall_automated"], "fpr": fpr}

    path = C.DERIVED / "validation.json"
    path.write_text(json.dumps(jsonable(out), indent=1))
    print(f"TEST  n={t['n_labelled']} classified={t['n_classified']} "
          f"recall(auto)={t['recall_automated']:.2f} recall(human)={t['recall_human']:.2f} "
          f"bal.acc={t['balanced_accuracy']:.2f} AUC={t.get('auc', float('nan')):.2f}")


if __name__ == "__main__":
    run()
