"""Offline tests: no network and no private trading account data."""
import importlib.util
import sys
import unittest
from pathlib import Path

scripts = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(scripts))
import update_market_signals as mod


class MarketSignalTests(unittest.TestCase):
    def test_half_step_rounding_and_clamp(self):
        self.assertEqual(mod.half(3.25), 3.0)
        self.assertEqual(mod.half(3.3), 3.5)
        self.assertEqual(mod.half(-10), 0.0)
        self.assertEqual(mod.half(10), 5.0)

    def test_index_scoring_bull_and_bear(self):
        rising = [{"date": "2026-01-01", "close": 100 + i,
                   "amount": 1e11} for i in range(270)]
        falling = [{"date": "2026-01-01", "close": 600 - i,
                    "amount": 1e11} for i in range(270)]
        self.assertEqual(mod.index_score(rising)["score"], 5.0)
        self.assertEqual(mod.index_score(falling)["score"], 0.0)

    def test_index_scoring_requires_long_history(self):
        with self.assertRaises(ValueError):
            mod.index_score([{"date": "2026-01-01", "close": 100}] * 40)

    def test_index_weight_sum(self):
        self.assertAlmostEqual(sum(x[3] for x in mod.INDICES), 1.0)
        self.assertEqual([x[0] for x in mod.INDICES],
                         ["000300", "000905", "000852", "932000"])


if __name__ == "__main__":
    unittest.main()
