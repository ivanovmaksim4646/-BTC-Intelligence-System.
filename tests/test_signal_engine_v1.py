import datetime as dt
import unittest
from src.signal_engine_v1 import evaluate

NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)

def fixtures(direction="long"):
    report = {
        "report_data_status": "ready", "collected_at_utc": "2026-11-26T11:59:00Z",
        "order_flow": {"M5": {"coverage": {"spot": "complete", "futures": "complete"},
                              "spot_delta": 2 if direction == "long" else -2,
                              "futures_delta": 3 if direction == "long" else -3}}
    }
    candidates = {"timeframes": {"M5": {"status": "watch_candidate", "direction": direction}}}
    event = {"source": "btc-intelligence-tv-v2", "event": "m5_bullish_bos" if direction == "long" else "m5_bearish_shift",
             "symbol": "BINGX:BTCUSDT.P", "timeframe": "5",
             "time_ms": int((NOW - dt.timedelta(minutes=2)).timestamp() * 1000)}
    return report, candidates, [event]

class SignalEngineTests(unittest.TestCase):
    def test_watch_is_not_trade_signal(self):
        got = evaluate(*fixtures(), now=NOW)
        self.assertEqual(got["decision"], "LONG_WATCH")
        self.assertFalse(got["entry_signal"])
        self.assertIsNone(got["trade_signal"])
        self.assertIsNone(got["rr"])

    def test_short_watch(self):
        self.assertEqual(evaluate(*fixtures("short"), now=NOW)["decision"], "SHORT_WATCH")

    def test_stale_report_fails_closed(self):
        r,c,e = fixtures()
        r["collected_at_utc"] = "2026-11-26T11:30:00Z"
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

    def test_incomplete_orderflow_fails_closed(self):
        r,c,e = fixtures()
        r["order_flow"]["M5"]["coverage"]["spot"] = "partial"
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

    def test_legacy_event_cannot_confirm_v2(self):
        r,c,e = fixtures()
        e[0]["source"] = "btc-intelligence-tv-v1"
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

    def test_no_candidate_is_no_trade(self):
        r,c,e = fixtures()
        c["timeframes"]["M5"]["status"] = "no_structure_break"
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

    def test_stale_event_fails_closed(self):
        r,c,e = fixtures()
        e[0]["time_ms"] = int((NOW-dt.timedelta(minutes=20)).timestamp()*1000)
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

    def test_opposite_delta_fails_closed(self):
        r,c,e = fixtures()
        r["order_flow"]["M5"]["spot_delta"] = -1
        self.assertEqual(evaluate(r,c,e,now=NOW)["decision"], "NO_TRADE")

if __name__ == "__main__":
    unittest.main()
