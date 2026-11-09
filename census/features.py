"""Behavioural features computed from an account's own transaction history.

Nothing here looks at the account *name* or at any off-chain information: the classifier sees only
timing, success, call-shape and key-usage signals, so the independently-sourced validation labels
(see labels.py) are not circular.
"""
from __future__ import annotations

import base64
import json

import numpy as np

from . import config as C

NAN = float("nan")


def history_features(rows: list[dict], total_count: int | None = None) -> dict:
    """Timing / outcome features from `/v0/account` rows (any order)."""
    n = len(rows)
    out = {"n_obs": n, "txs_count_total": total_count if total_count is not None else n,
           "truncated": n >= C.HISTORY_LIMIT}
    blank = dict(span_days=NAN, rate_per_day=NAN, gap_median_s=NAN, gap_cv=NAN, periodic_share=NAN,
                 fast_share=NAN, rest_per_day=NAN, hour_coverage=NAN, fail_rate=NAN, fc_share=NAN,
                 delegated_share=NAN)
    if n < 2:
        out.update(blank)
        if n == 1:
            out.update(fail_rate=0.0 if rows[0].get("is_success", True) else 1.0)
        return out

    ts = np.sort(np.array([int(r["tx_block_timestamp"]) for r in rows], dtype=np.float64) / 1e9)
    gaps = np.diff(ts)
    span = float(ts[-1] - ts[0])
    med = float(np.median(gaps))
    mean = float(gaps.mean())
    tol = max(C.PERIODIC_TOLERANCE * med, 1.5)             # 1.5 s floor: block-time quantisation
    hours = {int((t % 86400) // 3600) for t in ts}

    out.update(
        span_days=span / 86400,
        rate_per_day=n / (span / 86400) if span > 0 else NAN,
        gap_median_s=med,
        gap_cv=float(gaps.std() / mean) if mean > 0 else NAN,
        periodic_share=float(np.mean(np.abs(gaps - med) <= tol)) if med > 0 else NAN,
        fast_share=float(np.mean(gaps <= C.FAST_GAP_SECONDS)),
        # sleeping pattern: silent stretches >= 5h per day of observed span. Only meaningful over >= 2 days.
        rest_per_day=float(np.sum(gaps >= C.REST_GAP_SECONDS) / (span / 86400)) if span >= 2 * 86400 else NAN,
        hour_coverage=len(hours) / 24 if span >= 2 * 86400 else NAN,
        fail_rate=float(np.mean([not r.get("is_success", True) for r in rows])),
        fc_share=float(np.mean([bool(r.get("is_function_call")) for r in rows])),
        delegated_share=float(np.mean([bool(r.get("is_delegated_signer")) for r in rows])),
    )
    return out


# --- call shape, from full transaction objects ---------------------------------------------------------

def _decode_args(b64: str) -> bytes:
    try:
        return base64.b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception:
        return b""


def tx_shape(full: dict) -> dict:
    """Call-shape descriptors for one full transaction (`/v0/transactions` element)."""
    tx = full["transaction"]
    actions = tx.get("actions", [])
    delegated = False
    if len(actions) == 1 and "Delegate" in actions[0]:       # meta-transaction: the user's actions are inside
        actions = actions[0]["Delegate"]["delegate_action"]["actions"]
        delegated = True
    kinds, methods, intents = [], [], tx.get("receiver_id") == C.INTENTS_CONTRACT
    for a in actions:
        kind = next(iter(a)) if isinstance(a, dict) else str(a)
        kinds.append(kind)
        if kind == "FunctionCall":
            fc = a["FunctionCall"]
            methods.append(fc["method_name"])
            if fc["method_name"] == "execute_intents" or C.INTENTS_CONTRACT.encode() in _decode_args(fc.get("args", "")):
                intents = True
    single_fc_no_deposit = (
        len(actions) == 1 and kinds[0] == "FunctionCall" and actions[0]["FunctionCall"].get("deposit", "0") == "0"
    )
    return {
        "n_actions": len(actions), "delegated": delegated, "kind": kinds[0] if kinds else "",
        "method": methods[0] if methods else "", "touches_intents": intents,
        # A function-call access key may only sign one FunctionCall action with zero deposit. Consistency
        # with that is necessary (not sufficient) for FC-key use; validated against the real key in labels.py.
        "fc_key_consistent": bool(single_fc_no_deposit),
    }


def json_dumps_compact(o) -> str:
    return json.dumps(o, separators=(",", ":"))
