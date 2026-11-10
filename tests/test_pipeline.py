"""Offline tests for the sampling cap, label rules, thesis verdict logic and insights."""
import unittest

import numpy as np
import pandas as pd

from census import config as C
from census.analyze import _boot_scaled, sec_per_block
from census.util import ranked, top_value
from census.collect import cap_txs, needed_profiles
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


class ProfileAlignmentTests(unittest.TestCase):
    def test_relayer_profiles_are_paired_with_their_own_month(self):
        df = pd.DataFrame([
            {"period": "2026-01", "real_signer": "u1", "payer": "u1"},
            {"period": "2026-02", "real_signer": "u2", "payer": "u2"},
            {"period": "2026-03", "real_signer": "u3", "payer": "relayer.near"},
            {"period": "2026-04", "real_signer": "u4", "payer": "relayer.near"},
        ])
        need = needed_profiles(df)
        self.assertEqual(need["top"], {("2026-03", "relayer.near"), ("2026-04", "relayer.near")})
        self.assertEqual(len(need["real"]), 4)


class AbsoluteLevelTests(unittest.TestCase):
    def test_absolute_level_is_share_times_header_mean(self):
        rng = np.random.default_rng(0)
        num, den = np.full(45, 3.0), np.full(45, 10.0)           # 30% of sampled txs are automated
        scale = np.full(45, 50.0)                                # header says 50 txs per block
        point, lo, hi = _boot_scaled(num, den, scale, rng)
        self.assertAlmostEqual(point, 15.0)                      # 0.3 x 50
        self.assertLessEqual(lo, point)
        self.assertGreaterEqual(hi, point)

    def test_share_up_while_level_down_is_distinguishable(self):
        rng = np.random.default_rng(1)
        before = _boot_scaled(np.full(45, 2.0), np.full(45, 10.0), np.full(45, 80.0), rng)[0]   # 20% of 80/block = 16
        after = _boot_scaled(np.full(45, 6.0), np.full(45, 10.0), np.full(45, 5.0), rng)[0]     # 60% of 5/block = 3
        self.assertLess(after, before)                           # the share tripled but the level fell

    def test_block_time_is_measured_from_heights_and_timestamps(self):
        b = pd.DataFrame({"height": [1000, 2000, 3000], "ts": [0, 1220, 2440]})
        self.assertAlmostEqual(sec_per_block(b), 1.22)
        self.assertIsNone(sec_per_block(pd.DataFrame({"height": [5], "ts": [1]})))


class DeterministicTieTests(unittest.TestCase):
    """Rankings must not depend on how a pandas version orders ties (a tie once changed an output table between CI machines)."""

    def test_top_value_breaks_ties_alphabetically(self):
        self.assertEqual(top_value(pd.Series(["b", "a", "b", "a", "c"])), "a")
        self.assertEqual(top_value(pd.Series(["z", "y", "y", "z"])), "y")

    def test_ranked_is_a_total_order(self):
        df = pd.DataFrame({"txs": [5, 5, 5, 9], "fee": [1.0, 1.0, 2.0, 0.1]}, index=pd.Index(["c", "a", "b", "z"], name="acct"))
        order = list(ranked(df, "txs", "acct", ["fee"]).index)
        self.assertEqual(order, ["z", "b", "a", "c"])                 # by txs, then fee, then name ascending
        self.assertEqual(order, list(ranked(df.iloc[::-1], "txs", "acct", ["fee"]).index))   # input order is irrelevant


if __name__ == "__main__":
    unittest.main()
