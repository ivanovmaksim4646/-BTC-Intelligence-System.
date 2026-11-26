import unittest
from src.okx_rest_pagination_probe import probe

def row(i,t,side="buy"):
    return {"instId":"BTC-USDT","tradeId":str(i),"ts":str(t),"side":side,"sz":"0.1"}

class ProbeTests(unittest.TestCase):
    def test_boundaries(self):
        pages=iter([[row(5,600001),row(4,599999)],[row(3,300000,"sell"),row(2,299999)]])
        r=probe("BTC-USDT",lambda _:next(pages),600000)
        self.assertTrue(r["both_time_boundaries_observed"])
        self.assertEqual(r["observed_delta_native"],"0.0")
        self.assertIsNone(r["complete_delta_btc"])
    def test_budget(self):
        r=probe("BTC-USDT",lambda _:[row(5,600001)],600000,1)
        self.assertFalse(r["both_time_boundaries_observed"])
    def test_repeated_cursor(self):
        with self.assertRaises(ValueError):
            probe("BTC-USDT",lambda _:[row(5,600001)],600000)
