import datetime as dt
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "market_analysis.py"
SPEC = importlib.util.spec_from_file_location("market_analysis", PATH)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)
NOW = dt.datetime(2026, 11, 24, 17, 5, tzinfo=dt.timezone.utc)

def sample():
    sp = {"window_start_utc": "2026-11-24T16:00:00Z",
          "window_end_utc": "2026-11-24T17:00:00Z",
          "coverage": "complete", "buy_volume": 20.0, "sell_volume": 5.0, "delta": 15.0}
    ft = dict(sp, buy_volume=3.0, sell_volume=12.0, delta=-9.0)
    return {"collected_at_utc": "2026-11-24T17:01:00Z",
            "health": {"freshness_limit_seconds": 5400},
            "order_flow": {"spot": {"H1": sp}, "futures": {"H1": ft}},
            "derivatives": {"open_interest": {"value": 2000.0, "change": {"H1": 20.0}}}}

class MarketAnalysisTests(unittest.TestCase):
    def test_divergence_is_observation_not_signal(self):
        out = analysis.analyse(sample(), NOW)
        self.assertEqual(out["timeframes"]["H1"]["observation"], "spot_buy_futures_sell_divergence")
        self.assertIsNone(out["trade_signal"])

    def test_stale_rejects(self):
        data = sample()
        data["collected_at_utc"] = "2026-11-24T12:00:00Z"
        self.assertFalse(analysis.analyse(data, NOW)["fresh"])
        self.assertEqual(analysis.analyse(data, NOW)["timeframes"]["H1"]["observation"], "unavailable")

    def test_window_mismatch_rejects(self):
        data = sample()
        data["order_flow"]["futures"]["H1"]["window_start_utc"] = "2026-11-24T15:00:00Z"
        self.assertEqual(analysis.analyse(data, NOW)["timeframes"]["H1"]["observation"], "unavailable")

    def test_partial_rejects(self):
        data = sample()
        data["order_flow"]["spot"]["H1"]["coverage"] = "partial"
        self.assertEqual(analysis.analyse(data, NOW)["timeframes"]["H1"]["observation"], "unavailable")

    def test_zero_volume_rejects(self):
        data = sample()
        data["order_flow"]["spot"]["H1"].update(buy_volume=0, sell_volume=0)
        self.assertEqual(analysis.analyse(data, NOW)["timeframes"]["H1"]["observation"], "unavailable")

    def test_future_timestamp_rejects(self):
        data = sample()
        data["collected_at_utc"] = "2026-11-24T17:10:00Z"
        self.assertFalse(analysis.analyse(data, NOW)["fresh"])

if __name__ == "__main__":
    unittest.main()
