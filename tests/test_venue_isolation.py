import datetime as dt
import unittest
from src.binance_poi_qm_v1 import evaluate

NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)

def snapshot(venue):
    periods={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800}
    return {"source":venue,"status":"verified","collected_at_utc":NOW.isoformat(),
            "timeframes":{k:{"status":"ok","bars":[
                {"t":i*n,"o":100,"h":105,"l":95,"c":102} for i in range(35)]}
                          for k,n in periods.items()}}

class VenueIsolationTests(unittest.TestCase):
    def test_bingx_never_passes_binance_source_check(self):
        x=evaluate(snapshot("BingX USD-M Perpetual BTC-USDT"),NOW)
        self.assertEqual(x["observations"],[])
        self.assertIn("missing_or_stale_verified_futures_candles",x["reasons"])

    def test_bingx_explicit_same_venue_is_research_only(self):
        v="BingX USD-M Perpetual BTC-USDT"
        x=evaluate(snapshot(v),NOW,expected_source=v)
        self.assertEqual(x["source"],v)
        self.assertEqual(x["decision"],"NO_TRADE")
        self.assertIsNone(x["entry"])
        self.assertIsNone(x["sl"])
        self.assertIsNone(x["tp"])
        self.assertIsNone(x["rr"])

    def test_binance_cannot_pass_bingx_source_check(self):
        v="BingX USD-M Perpetual BTC-USDT"
        x=evaluate(snapshot("Binance USD-M Futures BTCUSDT PERPETUAL"),NOW,expected_source=v)
        self.assertEqual(x["observations"],[])
        self.assertIn("missing_or_stale_verified_futures_candles",x["reasons"])
if __name__=="__main__":unittest.main()
