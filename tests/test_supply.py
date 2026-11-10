"""Offline tests for the supply, step-detection and value-capture maths, and the browser-vs-pipeline classifier parity."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from census import supply as S

SPB = 0.6          # seconds per block in the synthetic data


def synthetic_blocks(period: str, net_per_s: float, fee_per_block: float, version: int, n: int = 45, start_ts: int = 1_700_000_000) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    ts = np.sort(rng.integers(start_ts, start_ts + 2_000_000, n))
    return pd.DataFrame({"period": period, "height": (ts / SPB).astype(int), "ts": ts, "num_tx": 5, "tokens_burnt": fee_per_block,
                         "total_supply": 1_000_000_000 + net_per_s * (ts - ts.min()), "protocol_version": version})


class SupplyTests(unittest.TestCase):
    def test_net_issuance_slope_is_recovered(self):
        rows, _ = S.monthly(synthetic_blocks("2026-01", net_per_s=2.0, fee_per_block=0.01, version=88))
        self.assertAlmostEqual(rows[0]["net_issuance_ps"], 2.0, places=6)
        lo, hi = rows[0]["net_issuance_ps_ci"]
        self.assertLessEqual(lo, 2.0 + 1e-9)
        self.assertGreaterEqual(hi, 2.0 - 1e-9)

    def test_burn_share_depends_on_protocol_version(self):
        pre, _ = S.monthly(synthetic_blocks("2026-01", 1.0, 0.01, version=86))
        post, _ = S.monthly(synthetic_blocks("2026-01", 1.0, 0.01, version=88))
        self.assertAlmostEqual(pre[0]["burn_ps"] / pre[0]["fees_ps"], 0.70, places=6)      # contracts took 30% up to v86
        self.assertAlmostEqual(post[0]["burn_ps"] / post[0]["fees_ps"], 1.00, places=6)    # all burned from v87
        self.assertTrue(post[0]["saw_v87"])
        self.assertFalse(pre[0]["saw_v87"])

    def test_gross_issuance_is_net_plus_burn(self):
        r, _ = S.monthly(synthetic_blocks("2026-01", 1.5, 0.02, version=88))
        self.assertAlmostEqual(r[0]["gross_issuance_ps"], r[0]["net_issuance_ps"] + r[0]["burn_ps"])
        self.assertAlmostEqual(r[0]["burn_cover"], r[0]["burn_ps"] / r[0]["gross_issuance_ps"])


class StepTests(unittest.TestCase):
    def rows(self, spec):
        return [{"period": p, "net_issuance_ps": v, "net_issuance_ps_ci": [v * .98, v * 1.02]} for p, v in spec]

    def test_finds_largest_log_step_between_consecutive_months(self):
        st = S.largest_step(self.rows([("2025-09", 2.0), ("2025-10", 2.0), ("2025-11", 1.0), ("2025-12", 1.05)]))
        self.assertEqual((st["from"], st["to"]), ("2025-10", "2025-11"))
        self.assertTrue(st["disjoint_intervals"])
        self.assertAlmostEqual(st["relative_change"], -0.5)

    def test_gaps_between_sparse_months_are_never_a_step(self):
        st = S.largest_step(self.rows([("2022-01", 1.0), ("2023-07", 9.0), ("2023-08", 9.1)]))      # the 2022 -> 2023 jump spans 18 months
        self.assertEqual((st["from"], st["to"]), ("2023-07", "2023-08"))

    def test_a_fall_to_a_fifth_outranks_a_doubling(self):
        spec = [("2024-01", 10.0), ("2024-02", 20.0), ("2024-03", 20.0), ("2024-04", 4.0)]
        ci = lambda r: r["net_issuance_ps_ci"]
        self.assertEqual(S.largest_step(self.rows(spec), "net_issuance_ps", ci)["to"], "2024-04")
        self.assertEqual(S.largest_step(self.rows(spec), "net_issuance_ps", ci, direction=+1)["to"], "2024-02")


class ValueCaptureTests(unittest.TestCase):
    def test_revenue_cover_is_revenue_over_issuance_in_usd(self):
        blocks = pd.concat([synthetic_blocks("2026-01", 1.0, 0.0, 88), synthetic_blocks("2026-02", 1.0, 0.0, 88)])
        rows, keep = S.monthly(blocks)
        days = pd.date_range("2025-12-20", "2026-03-05").strftime("%Y-%m-%d")
        snap = {"retrieved_on": "2026-03-06", "methodology": {}, "fees_usd": {d: 5000.0 for d in days}, "revenue_usd": {d: 2000.0 for d in days}}
        price = {d: 2.0 for d in days}
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "defillama_near_intents.json").write_text(json.dumps(snap))
            (t / "defillama_near_price.json").write_text(json.dumps({"usd": price}))
            old, S.EXTERNAL = S.EXTERNAL, t
            try:
                v = S.value_capture(rows, keep, {"a": ["2026-01"], "b": ["2026-02"]})
            finally:
                S.EXTERNAL = old
        expect = 2000.0 / (1.0 * 86400 * 2.0)                  # revenue / (gross issuance per day x price)
        self.assertAlmostEqual(v["rows"][-1]["revenue_cover"], expect, places=4)
        self.assertEqual(v["last_full_day"], "2026-03-04")     # the newest day of the snapshot is treated as partial and dropped


class BrowserParityTests(unittest.TestCase):
    """The dashboard's in-browser classifier must score exactly like census/classify.py. Skipped when no browser is available."""

    def test_js_matches_python_on_real_accounts(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            self.skipTest("playwright not installed")
        root = Path(__file__).resolve().parent.parent
        fx = json.loads((Path(__file__).parent / "fixtures" / "live_parity.json").read_text())
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome")
            except Exception:
                try:
                    browser = pw.chromium.launch(channel="msedge")
                except Exception:
                    self.skipTest("no Chrome or Edge available")
            page = browser.new_page()
            page.goto((root / "docs" / "index.html").as_uri())
            page.wait_for_function("window.__census !== undefined")
            bad = page.evaluate("""(fx) => {
                const near = (a, b) => (a == null && (b == null || Number.isNaN(b))) || (b == null && Number.isNaN(a)) || Math.abs(a - b) < 1e-9, out = [];
                for (const c of fx) {
                    const r = window.__census.classifyRows(c.rows.map(x => ({ ts: x[0], ok: !!x[1], fc: !!x[2], deleg: !!x[3] })), c.total), e = c.expected, f = r.features;
                    if (r.score !== e.score || r.klass !== e.klass || JSON.stringify(r.fired) !== JSON.stringify(e.fired)) out.push(c.account);
                    for (const k of ['n_obs', 'rate_per_day', 'fast_share', 'periodic_share', 'rest_per_day', 'hour_coverage', 'fail_rate']) if (!near(f[k], e[k])) out.push(c.account + ':' + k);
                }
                return out; }""", fx)
            browser.close()
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
