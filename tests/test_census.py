"""Offline tests: synthetic accounts with known behaviour. Run: python -m unittest discover -s tests -v"""
import base64
import json
import math
import random
import unittest

import numpy as np
import pandas as pd

from census import config as C
from census.analyze import _bootstrap, trend_forecast
from census.classify import classify_frame, score
from census.features import history_features, tx_shape
from census.heights import to_ns
from census.labels import looks_automated
from census.util import jsonable
from census.validate import auc, rogan_gladen, split_of, wilson

DAY = 86400


def rows(timestamps, success=True, fc=True):
    return [{"tx_block_timestamp": str(int(t * 1e9)), "is_success": success, "is_function_call": fc,
             "is_delegated_signer": False} for t in timestamps]


def cron_bot(days=3, every=60):
    return rows([i * every for i in range(int(days * DAY / every))][-200:])


def human(days=10, seed=1):
    rng = random.Random(seed)
    ts = []
    for d in range(days):                       # awake 09:00-18:00 UTC, a handful of txs per day
        ts += [d * DAY + 9 * 3600 + rng.random() * 9 * 3600 for _ in range(rng.randint(3, 8))]
    return rows(sorted(ts))


class FeatureTests(unittest.TestCase):
    def test_cron_bot_is_periodic_and_never_rests(self):
        f = history_features(cron_bot(days=3, every=60)[-200:])
        self.assertGreater(f["periodic_share"], 0.95)
        self.assertEqual(f["rest_per_day"] if not math.isnan(f["rest_per_day"]) else 0, 0)
        self.assertLess(f["gap_cv"], 0.1)

    def test_human_rests_every_day(self):
        f = history_features(human())
        self.assertGreater(f["rest_per_day"], 0.8)
        self.assertLess(f["hour_coverage"], 0.6)

    def test_single_tx_has_no_timing_features(self):
        f = history_features(rows([1000.0]))
        self.assertEqual(f["n_obs"], 1)
        self.assertTrue(math.isnan(f["gap_cv"]))

    def test_failure_rate(self):
        f = history_features(rows([0, 10, 20, 30], success=False))
        self.assertEqual(f["fail_rate"], 1.0)


class ClassifierTests(unittest.TestCase):
    def _klass(self, r, total=None):
        df = pd.DataFrame([{**history_features(r, total)}])
        return classify_frame(df).iloc[0]

    def test_bot_human_and_abstention(self):
        bot = self._klass(cron_bot(days=3, every=2), total=500_000)
        self.assertEqual(bot["klass"], "automated")
        person = self._klass(human(), total=300)
        self.assertEqual(person["klass"], "human")
        few = self._klass(rows([0, 5, 9]))
        self.assertEqual(few["klass"], "low_activity")

    def test_score_is_explainable_and_bounded(self):
        s, fired = score({"txs_count_total": 10**6, "rate_per_day": 10**4, "fast_share": 0.9,
                          "periodic_share": 0.9, "rest_per_day": 0.0, "hour_coverage": 1.0, "fc_key_share": 1.0})
        self.assertEqual(s, 100)
        self.assertIn("machine_speed_gaps", fired)

    def test_names_never_reach_the_classifier(self):
        import inspect
        from census import classify
        self.assertNotIn("account_id", inspect.getsource(classify.score))
        self.assertTrue(looks_automated("price-oracle.near"))
        self.assertFalse(looks_automated("alice.near"))


class ShapeTests(unittest.TestCase):
    def _tx(self, actions, receiver="app.near"):
        return {"transaction": {"receiver_id": receiver, "actions": actions}}

    def fc(self, method, deposit="0", args=b"{}"):
        return {"FunctionCall": {"method_name": method, "args": base64.b64encode(args).decode(), "gas": 1, "deposit": deposit}}

    def test_function_call_key_shape(self):
        s = tx_shape(self._tx([self.fc("claim")]))
        self.assertTrue(s["fc_key_consistent"])
        self.assertFalse(tx_shape(self._tx([self.fc("pay", deposit="1")]))["fc_key_consistent"])
        self.assertFalse(tx_shape(self._tx([self.fc("a"), self.fc("b")]))["fc_key_consistent"])

    def test_delegate_is_unwrapped(self):
        inner = {"Delegate": {"delegate_action": {"actions": [self.fc("l2_claim")]}}}
        s = tx_shape(self._tx([inner]))
        self.assertTrue(s["delegated"])
        self.assertEqual(s["method"], "l2_claim")

    def test_intents_detected_in_args(self):
        args = json.dumps({"receiver_id": "intents.near", "amount": "1"}).encode()
        self.assertTrue(tx_shape(self._tx([self.fc("ft_transfer_call", args=args)], "usdt.tether-token.near"))["touches_intents"])
        self.assertTrue(tx_shape(self._tx([], "intents.near"))["touches_intents"])


class StatsTests(unittest.TestCase):
    def test_wilson_contains_p_and_is_sane(self):
        lo, hi = wilson(80, 100)
        self.assertLess(lo, 0.8)
        self.assertGreater(hi, 0.8)
        self.assertTrue(math.isnan(wilson(0, 0)[0]))

    def test_auc_perfect_and_random(self):
        self.assertEqual(auc(np.array([1, 2, 8, 9.0]), np.array([0, 0, 1, 1])), 1.0)
        self.assertAlmostEqual(auc(np.array([1, 1, 1, 1.0]), np.array([0, 1, 0, 1])), 0.5)

    def test_rogan_gladen_recovers_prevalence(self):
        tpr, fpr, prev = 0.9, 0.1, 0.4
        observed = prev * tpr + (1 - prev) * fpr
        self.assertAlmostEqual(rogan_gladen(observed, tpr, fpr), prev, places=6)
        self.assertIsNone(rogan_gladen(0.5, 0.5, 0.5))      # uninformative classifier

    def test_split_is_deterministic_and_balanced(self):
        self.assertEqual(split_of("a.near"), split_of("a.near"))
        share = np.mean([split_of(f"acct{i}.near") == "test" for i in range(2000)])
        self.assertAlmostEqual(share, 0.5, delta=0.05)

    def test_bootstrap_interval_covers_truth_most_of_the_time(self):
        rng = np.random.default_rng(3)
        hits, trials, truth = 0, 60, 0.30
        for _ in range(trials):
            n_tx = rng.integers(1, 12, size=45)
            auto = rng.binomial(n_tx, truth)
            p, lo, hi, _ = _bootstrap(auto.astype(float), n_tx.astype(float), np.random.default_rng(int(rng.integers(1e9))))
            hits += lo <= truth <= hi
        self.assertGreaterEqual(hits / trials, 0.85)           # nominal 95%; allow small-sample slack

    def test_trend_forecast_detects_growth(self):
        periods = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 7)]
        rng = np.random.default_rng(0)
        draws = {p: np.clip(0.3 + 0.02 * i + rng.normal(0, 0.01, 500), 0.01, 0.99) for i, p in enumerate(periods)}
        f = trend_forecast(periods, draws, months=18, horizon=6)
        self.assertGreater(f["prob_slope_positive"], 0.99)
        self.assertGreater(f["share_p50"][-1], f["share_p50"][0])
        self.assertLessEqual(f["share_lo"][-1], f["share_p50"][-1])


class UtilTests(unittest.TestCase):
    def test_jsonable_strips_nan_and_numpy(self):
        out = jsonable({"a": float("nan"), "b": np.float64(1.5), "c": [np.int64(2)], "d": (1, float("inf"))})
        json.dumps(out, allow_nan=False)
        self.assertIsNone(out["a"])

    def test_to_ns(self):
        from datetime import datetime
        self.assertEqual(to_ns(datetime(1970, 1, 1)), 0)


if __name__ == "__main__":
    unittest.main()
