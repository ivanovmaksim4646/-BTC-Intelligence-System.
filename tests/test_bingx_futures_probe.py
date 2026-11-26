import datetime as dt
import unittest
from src.bingx_futures_probe import parse_response, collect

NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)
def payload(interval="5m",step=300):
    last=int(NOW.timestamp())-step
    return {"code":0,"msg":"","data":[{"time":(last-i*step)*1000,
        "open":"100","high":"102","low":"98","close":"101","volume":"2"}
        for i in range(35)]}
class BingXProbeTests(unittest.TestCase):
    def test_valid_close_candles(self):
        self.assertEqual(len(parse_response(payload(),"5m",int(NOW.timestamp()*1000))),35)
    def test_reject_bad_api_code(self):
        with self.assertRaises(ValueError):
            parse_response({"code":1001,"data":[]},"5m",int(NOW.timestamp()*1000))
    def test_reject_gaps(self):
        p=payload()
        p["data"].pop(5)
        with self.assertRaises(ValueError):
            parse_response(p,"5m",int(NOW.timestamp()*1000))
    def test_bad_ohlc(self):
        p=payload()
        p["data"][0]["high"]="50"
        with self.assertRaises(ValueError):
            parse_response(p,"5m",int(NOW.timestamp()*1000))
    def test_failed_venue_keeps_no_trade(self):
        def unavailable(tf):raise OSError("blocked")
        r=collect(NOW,unavailable)
        self.assertEqual(r["status"],"partial")
        self.assertIsNone(r["trade_signal"])
if __name__=="__main__":
    unittest.main()
