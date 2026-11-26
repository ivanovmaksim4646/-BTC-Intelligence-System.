import datetime as dt
import unittest
from src.market_breadth_macro_v1 import breadth,macro_series
NOW=dt.datetime(2026,11,26,12,tzinfo=dt.timezone.utc)
class ContextTests(unittest.TestCase):
    def test_breadth(self):
        r=breadth({"data":{"total_market_cap":{"usd":1000},"market_cap_percentage":{"btc":60,"eth":20},"updated_at":NOW.timestamp()}},NOW)
        self.assertAlmostEqual(r["total_ex_btc_eth_usd"],200)
    def test_stale(self):
        with self.assertRaises(ValueError):breadth({"data":{"total_market_cap":{"usd":1000},"market_cap_percentage":{"btc":60,"eth":20},"updated_at":0}},NOW)
    def test_macro(self):
        r=macro_series("observation_date,UNRATE\n2026-09-01,4.1\n2026-10-01,4.2\n","UNRATE",NOW)
        self.assertEqual(r["previous"],4.1)
        self.assertIsNone(r["consensus_forecast"])
