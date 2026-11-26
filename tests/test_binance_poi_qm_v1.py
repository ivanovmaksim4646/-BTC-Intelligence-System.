import datetime as dt
import unittest
from src.binance_futures_candles import parse_klines, collect, INTERVALS
from src.binance_poi_qm_v1 import evaluate, fvg_zones

NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)
def kline(t,step=300,o=100,h=105,l=95,c=102):
    ms=t*1000
    return [ms,str(o),str(h),str(l),str(c),"100",ms+step*1000-1]

def snapshot():
    return {"source":"Binance USD-M Futures BTCUSDT PERPETUAL",
            "status":"verified", "collected_at_utc":NOW.isoformat(),
            "timeframes":{tf:{"status":"ok","bars":[{"t":i*seconds,"o":100,
                   "h":105,"l":95,"c":102} for i in range(35)]}
                for tf,seconds in INTERVALS.items()}}

class BinanceFuturesTests(unittest.TestCase):
    def test_closed_only(self):
        now_ms=1800*1000
        bars=parse_klines([kline(0),kline(300),kline(600),kline(900)],300,now_ms)
        self.assertEqual(len(bars),4)
    def test_forming_excluded(self):
        bars=parse_klines([kline(0),kline(300),kline(600)],300,750000)
        self.assertEqual(len(bars),2)
    def test_gap_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_klines([kline(0),kline(600)],300,1000000)
    def test_week_starts_monday(self):
        monday=345600
        bars=parse_klines([kline(monday,604800),kline(monday+604800,604800)],604800,
                          (monday+2*604800)*1000)
        self.assertEqual(len(bars),2)
    def test_collector_fails_closed_on_api_error(self):
        def missing(tf):
            raise OSError("access denied")
        out=collect(NOW,missing)
        self.assertEqual(out["status"],"partial")
        self.assertEqual(len(out["errors"]),6)
    def test_malformed_ohlc_fails(self):
        with self.assertRaises(ValueError):
            parse_klines([kline(0,o=105,h=100)],300,300000)
    def test_zone_identification(self):
        bars=[{"t":0,"h":102,"l":98},
              {"t":300,"h":104,"l":101},
              {"t":600,"h":108,"l":105}]
        self.assertEqual(fvg_zones(bars)[0]["low"],102)
    def test_no_trade_on_full_mock_history(self):
        out=evaluate(snapshot(),NOW)
        self.assertEqual(out["decision"],"NO_TRADE")
        self.assertIsNone(out["entry"])
        self.assertIsNone(out["rr"])
    def test_partial_source_blocks(self):
        s=snapshot()
        s["status"]="partial"
        self.assertEqual(evaluate(s,NOW)["observations"],[])
    def test_stale_snapshot_blocks(self):
        s=snapshot()
        s["collected_at_utc"]="2026-11-26T10:00:00Z"
        self.assertEqual(evaluate(s,NOW)["observations"],[])

if __name__=="__main__":
    unittest.main()
