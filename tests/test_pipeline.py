"""Offline tests for the sampling cap, label rules, thesis verdict logic and insights."""
import unittest

import numpy as np
import pandas as pd

from census import config as C
from census.collect import cap_txs
from census.insights import hourly
from census.labels import human_exclusion, looks_automated
from census.thesis import INCONCLUSIVE, NOT, SUPPORTED, _diff_verdict, evaluate


class CapTests(unittest.TestCase):
    def frame(self, n_a=500, n_b=50):
        rows = [{"period": "2026-01", "hash": f"a{i}"} for i in range(n_a)] + [{"period": "2026-02", "hash": f"b{i}"} for i in range(n_b)]
        return pd.DataFrame(rows)

    def test_cap_limits_busy_months_only(self):
        out = cap_txs(self.frame())
        counts = out.groupby("period").size()
        self.assertEqual(counts["2026-01"], C.MAX_TX_PER_PERIOD)
        self.assertEqual(counts["2026-02"], 50)

    def test_cap_is_deterministic_and_idempotent(self):
        a, b = cap_txs(self.frame()), cap_txs(self.frame())
        self.assertTrue(a.equals(b))
        self.assertTrue(cap_txs(a).equals(a))          # re-applying changes nothing, so old and new runs agree


class LabelRuleTests(unittest.TestCase):
    def test_human_exclusions(self):
        self.assertEqual(human_exclusion("5310105456.tg"), "telegram_mini_app_account")
        self.assertEqual(human_exclusion("a" * 64), "implicit_hex_account_unverifiable_owner")
        self.assertEqual(human_exclusion("chill.frigid_degen5.user.intear.near"), "subaccount_or_app_generated_namespace")
        self.assertEqual(human_exclusion("treasury-factory.near"), "organisation_or_app_name")
        self.assertIsNone(human_exclusion("alice.near"))

    def test_declared_roles(self):
        for name in ("stakin-mpc.near", "watcher03.ref-watchdog.near", "omni-relayer.bridge.near", "pyth-bot.ref-labs.near"):
            self.assertTrue(looks_automated(name), name)
        for name in ("alice.near", "botaciousnimbus.near"):      # a handle that merely contains 'bot' as a prefix is not a declared role
            self.assertFalse(looks_automated(name), name)


class ThesisTests(unittest.TestCase):
    def test_diff_verdict_follows_the_interval(self):
        self.assertEqual(_diff_verdict({"diff_lo": 0.01, "diff_hi": 0.10}), SUPPORTED)
        self.assertEqual(_diff_verdict({"diff_lo": -0.10, "diff_hi": -0.01}), NOT)
        self.assertEqual(_diff_verdict({"diff_lo": -0.05, "diff_hi": 0.05}), INCONCLUSIVE)
        self.assertEqual(_diff_verdict(None), INCONCLUSIVE)

    def res(self, point, lo, hi):
        m = {"tx_auto": {"point": point, "lo": lo, "hi": hi}, "tx_auto_t40": {"point": point + .1, "lo": 0, "hi": 1},
             "tx_auto_t60": {"point": point - .1, "lo": 0, "hi": 1}, "fee_init_auto": {"point": .5, "lo": .4, "hi": .6},
             "fee_paid_auto": {"point": .6, "lo": .5, "hi": .7}, "relayed": {"point": .4, "lo": .3, "hi": .5}}
        return {"latest_window": {"periods": ["2026-01", "2026-06"], "metrics": m}, "windows": None, "concentration": {}}

    def verdict(self, claims, cid):
        return next(c["verdict"] for c in claims if c["id"] == cid)

    def test_level_claim_flips_with_the_interval(self):
        self.assertEqual(self.verdict(evaluate(self.res(.6, .55, .65), {}), "C1"), SUPPORTED)
        self.assertEqual(self.verdict(evaluate(self.res(.4, .35, .45), {}), "C1"), NOT)
        self.assertEqual(self.verdict(evaluate(self.res(.5, .45, .55), {}), "C1"), INCONCLUSIVE)

    def test_robustness_claim_reports_sensitivity(self):
        r = self.res(.5, .45, .55)
        r["latest_window"]["metrics"]["tx_auto_t40"]["point"] = .8       # a 40-point spread across cut-offs
        self.assertEqual(self.verdict(evaluate(r, {}), "C6"), NOT)

    def test_no_validation_means_inconclusive_not_supported(self):
        self.assertEqual(self.verdict(evaluate(self.res(.6, .55, .65), {}), "C7"), INCONCLUSIVE)


class InsightTests(unittest.TestCase):
    def test_hourly_profile_separates_rhythm_from_flat(self):
        rng = np.random.default_rng(0)
        human = [{"period": "p", "ts": int(h * 3600 + 5), "init_class": "human"} for h in rng.choice(range(8, 18), 400)]
        auto = [{"period": "p", "ts": int(h * 3600 + 5), "init_class": "automated"} for h in rng.integers(0, 24, 400)]
        out = hourly(pd.DataFrame(human + auto), ["p"])
        self.assertLess(out["automated"]["busiest_6h_share"], out["human"]["busiest_6h_share"])
        self.assertEqual(out["human"]["hours_with_activity"], 10)
        self.assertEqual(len(out["automated"]["share"]), 24)
        self.assertEqual(out["rhythm_verdict"], "human_more_rhythmic")

    def test_rhythm_verdict_is_null_when_classes_look_alike(self):
        rng = np.random.default_rng(1)
        rows = [{"period": "p", "ts": int(h * 3600), "init_class": k} for k in ("human", "automated") for h in rng.integers(0, 24, 300)]
        self.assertEqual(hourly(pd.DataFrame(rows), ["p"])["rhythm_verdict"], "no_clear_difference")


if __name__ == "__main__":
    unittest.main()
