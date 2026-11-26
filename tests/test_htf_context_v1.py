import datetime as dt
import unittest
from src.htf_context_v1 import build

NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)

def base():
    return {"source":"Kraken Spot XBTUSD","timeframes":{
        "H1":{"status":"ok","latest_closed_utc":"2026-11-26T10:00:00Z",
              "last_high":100,"last_low":90,"last_close":95,
              "fvg":[{"kind":"bullish_fvg","low":91,"high":93,"formed_at":42}]},
        "H4":{"status":"ok","latest_closed_utc":"2026-11-26T08:00:00Z",
              "last_high":101,"last_low":89,"last_close":96},
        "D1":{"status":"ok","latest_closed_utc":"2026-11-25T00:00:00Z",
              "last_high":105,"last_low":80,"last_close":95}}}

class TestHTF(unittest.TestCase):
    def test_clean_levels_are_observational(self):
        out=build(base(),NOW)
        self.assertEqual(out["timeframes"]["H1"]["status"],"observed")
        self.assertEqual(out["timeframes"]["H1"]["fvg"][0]["mitigation_status"],"unknown")
        self.assertIsNone(out["trade_signal"])
        self.assertFalse(out["futures_chart_validated"])
    def test_stale_data_unavailable(self):
        x=base();x["timeframes"]["H1"]["latest_closed_utc"]="2026-11-25T00:00:00Z"
        self.assertEqual(build(x,NOW)["timeframes"]["H1"]["status"],"unavailable")
    def test_future_closed_candle_unavailable(self):
        x=base();x["timeframes"]["H4"]["latest_closed_utc"]="2026-11-26T12:00:00Z"
        self.assertEqual(build(x,NOW)["timeframes"]["H4"]["status"],"unavailable")
    def test_bad_ohlc_unavailable(self):
        x=base();x["timeframes"]["H1"]["last_close"]=200
        self.assertEqual(build(x,NOW)["timeframes"]["H1"]["status"],"unavailable")
    def test_bad_gap_ignored(self):
        x=base();x["timeframes"]["H1"]["fvg"].append({"kind":"bearish_fvg","low":99,"high":80})
        self.assertEqual(len(build(x,NOW)["timeframes"]["H1"]["fvg"]),1)

if __name__=="__main__":
    unittest.main()
