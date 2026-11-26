import unittest
from src.tradingview_validation import validate

NOW = 1795688100000
BASE = {
    "source": "btc-intelligence-tv-v2", "event": "m5_bullish_break",
    "symbol": "BINGX:BTCUSDT.P", "timeframe": "5",
    "time_ms": NOW, "price": 60500.0,
}
V2 = {**BASE, "level": 60480.0, "level_kind": "pivot_high", "volume": 15.0}


class TradingViewValidationTests(unittest.TestCase):
    def test_accept_v2_close_break(self):
        self.assertEqual(validate(V2, NOW)["event"], "m5_bullish_break")

    def test_accept_old_inside_bar(self):
        old = {
            **BASE, "source": "btc-intelligence-tv-v1", "event": "h1_inside_bar",
            "mother_low": 59000, "inside_low": 59500,
            "inside_high": 61000, "mother_high": 61500,
        }
        self.assertEqual(validate(old, NOW)["event"], "h1_inside_bar")

    def test_reject_fake_volume(self):
        with self.assertRaises(ValueError):
            validate({**V2, "volume": -1}, NOW)

    def test_reject_invalid_level_type(self):
        with self.assertRaises(ValueError):
            validate({**V2, "level_kind": "pdh"}, NOW)

    def test_reject_extraneous_fields(self):
        with self.assertRaises(ValueError):
            validate({**V2, "trade": "buy"}, NOW)

    def test_reject_stale_timestamp(self):
        with self.assertRaises(ValueError):
            validate(V2, NOW + 20 * 60 * 1000)

    def test_reject_non_btc_symbol(self):
        with self.assertRaises(ValueError):
            validate({**V2, "symbol": "BINANCE:ETHUSDT"}, NOW)

    def test_reject_bool_price(self):
        with self.assertRaises(ValueError):
            validate({**V2, "price": True}, NOW)

    def test_reject_non_m5(self):
        with self.assertRaises(ValueError):
            validate({**V2, "timeframe": "15"}, NOW)
