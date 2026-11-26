import unittest,datetime as dt
from src.okx_confluence_v2 import evaluate,window
class ConfluenceTests(unittest.TestCase):
    def test_missing(self):
        r=evaluate({}, {}, {}, {})
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertIsNone(r["watch_direction"])
    def test_stale(self):
        r=evaluate({"source":"OKX BTC-USDT-SWAP","classification":"closed_okx_swing_structure_plus_sampled_liquidity_research","generated_at_utc":"2020-01-01T00:00:00Z"}, {}, {}, {})
        self.assertIn("fresh_verified_structure",r["missing"])
    def test_wrong_window(self):
        self.assertIsNone(window({"classification":"volume_reconciled_rest_research_only","end_ms":300000},"BTC-USDT","5m",600))
    def test_wrong_venue(self):
        r=evaluate({"source":"Kraken"}, {}, {}, {})
        self.assertIsNone(r["trade_signal"])
    def test_sampled_not_complete(self):
        self.assertIsNone(window({"classification":"partial_rest_flow_audit_only","end_ms":300000},"BTC-USDT","5m",300))
