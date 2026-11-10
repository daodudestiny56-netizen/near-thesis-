import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from census import predictions as P


class OutcomeTests(unittest.TestCase):
    def row(self, quantity, op, lo, hi=""):
        return {"quantity": quantity, "operator": op, "threshold": str(lo), "threshold_high": str(hi)}

    def res(self, **month):
        return {"monthly": [{"period": P.PERIOD, **month}], "supply": {"monthly": [{"period": P.PERIOD, **month}]}}

    def test_threshold_rules(self):
        self.assertTrue(P._holds(">=", 0.5, 0.5, None))
        self.assertFalse(P._holds("<", 20, 20, None))
        self.assertTrue(P._holds("between", 1.0, 0.95, 1.10))
        self.assertFalse(P._holds("between", 1.2, 0.95, 1.10))

    def test_confirmed_refuted_and_pending(self):
        r = self.row("automated_share_of_transactions", ">=", 0.5)
        self.assertEqual(P.evaluate(r, self.res(tx_auto=0.6))[0], "confirmed")
        self.assertEqual(P.evaluate(r, self.res(tx_auto=0.4))[0], "refuted")
        self.assertEqual(P.evaluate(r, {"monthly": [{"period": "2026-11", "tx_auto": 0.9}], "supply": {}})[0], "pending")   # no 2026-12 data yet

    def test_range_prediction(self):
        r = self.row("net_issuance_near_per_s", "between", 0.95, 1.10)
        self.assertEqual(P.evaluate(r, self.res(net_issuance_ps=1.02))[0], "confirmed")
        self.assertEqual(P.evaluate(r, self.res(net_issuance_ps=0.50))[0], "refuted")


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.csv, self.sha = self.tmp / "predictions.csv", self.tmp / "predictions.csv.sha256"
        self.csv.write_text("id,statement\nP1,test\n")
        self.sha.write_text(hashlib.sha256(self.csv.read_bytes()).hexdigest() + "  predictions.csv\n")

    def patched(self):
        return mock.patch.multiple(P, CSV=self.csv, SHA=self.sha, DIR=self.tmp)

    def test_freeze_refuses_to_overwrite(self):
        with self.patched(), self.assertRaises(SystemExit) as cm:
            P.freeze()
        self.assertIn("already exists", str(cm.exception))

    def test_a_changed_file_voids_the_pre_registration(self):
        self.csv.write_text("id,statement\nP1,test edited after the freeze\n")
        with self.patched(), mock.patch.object(P.json, "loads", return_value={}), self.assertRaises(SystemExit) as cm:
            P.run()
        self.assertIn("void", str(cm.exception))

    def test_committed_predictions_match_their_frozen_hash(self):
        root = Path(__file__).resolve().parent.parent / "predictions"
        digest = hashlib.sha256((root / "predictions.csv").read_bytes()).hexdigest()
        self.assertEqual(digest, (root / "predictions.csv.sha256").read_text().split()[0])


if __name__ == "__main__":
    unittest.main()
