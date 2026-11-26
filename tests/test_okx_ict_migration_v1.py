import datetime as dt
import unittest
from src.okx_futures_candles import parse_candles, collect, INTERVALS, SOURCE
from src.binance_poi_qm_v1 import evaluate
from src.source_budget_v1 import evaluate as budget_evaluate

NOW=dt.datetime(2026,11,26,12,40,tzinfo=dt.timezone.utc)
def rows(tf,now=NOW,n=40):
    sec=INTERVALS[tf][1]
    end=int(now.timestamp())//sec*sec
    if tf=="1w":
        end=(int(now.timestamp())-345600)//sec*sec+345600
    # last closed bar is end-sec; newly active forming bar at end.
    starts=[end-i*sec for i in range(n)]
    return [[str(t*1000),"100","106","95","101","100","10","1000",
             "0" if i==0 else "1"] for i,t in enumerate(starts)]
class OKXCandleTests(unittest.TestCase):
    def test_all_six_timeframes_closed(self):
        for tf in INTERVALS:
            with self.subTest(tf=tf):
                bars=parse_candles(rows(tf),tf,int(NOW.timestamp()*1000))
                self.assertEqual(len(bars),39)
                self.assertEqual(bars[-1]["t"],(int(NOW.timestamp())-345600)//604800*604800+345600-604800 if tf=="1w" else int(NOW.timestamp())//INTERVALS[tf][1]*INTERVALS[tf][1]-INTERVALS[tf][1])
    def test_recent_candle_must_be_confirmed(self):
        r=rows("5m")
        r[1][8]="0"
        self.assertEqual(len(parse_candles(r,"5m",int(NOW.timestamp()*1000))),38)
    def test_missing_bar_rejected(self):
        r=rows("5m")
        del r[10]
        with self.assertRaises(ValueError):
            parse_candles(r,"5m",int(NOW.timestamp()*1000))
    def test_partial_collector_fail_closed(self):
        out=collect(NOW,lambda tf: (_ for _ in ()).throw(OSError("blocked")) if tf=="4h" else rows(tf))
        self.assertEqual(out["status"],"partial")
        self.assertEqual(out["timeframes"]["4h"]["bars"],[])
        self.assertEqual(out["errors"]["4h"],"OSError")
    def test_future_confirmed_rejected(self):
        r=rows("5m")
        r[0][8]="1"
        with self.assertRaises(ValueError):
            parse_candles(r,"5m",int(NOW.timestamp()*1000))
    def test_wrong_week_alignment_rejected(self):
        r=rows("1w")
        r[3][0]=str(int(r[3][0])+86400000)
        with self.assertRaises(ValueError):
            parse_candles(r,"1w",int(NOW.timestamp()*1000))
    def test_okx_ict_only_same_source(self):
        snap=collect(NOW,lambda tf:rows(tf))
        self.assertEqual(snap["status"],"verified")
        self.assertEqual(snap["source"],SOURCE)
        research=evaluate(snap,NOW,expected_source=SOURCE)
        self.assertEqual(research["decision"],"NO_TRADE")
        self.assertIsNone(research["trade_signal"])
        bad=evaluate(snap,NOW,expected_source="BingX USD-M Perpetual BTC-USDT")
        self.assertEqual(bad["observations"],[])
        self.assertIn("missing_or_stale_verified_futures_candles",bad["reasons"])
    def test_guard_records_migrated_candles_but_retains_bingx(self):
        snap=collect(NOW,lambda tf:rows(tf))
        study=evaluate(snap,NOW,expected_source=SOURCE)
        result=budget_evaluate({}, {}, NOW,okx_candles=snap,okx_ict=study)
        self.assertTrue(result["okx_features"]["closed_candles_5m_15m_1h_4h_1d_1w"])
        self.assertTrue(result["okx_features"]["okx_ict_observations_available"])
        self.assertFalse(result["okx_features"]["validated_okx_poi_qm_ifvg"])
        self.assertFalse(result["switch_approved"])
        self.assertEqual(result["decision"],"RETAIN_BINGX")
    def test_stale_data(self):
        r=rows("5m")
        later=int(NOW.timestamp()*1000)+900000
        with self.assertRaises(ValueError):
            parse_candles(r,"5m",later)
    def test_broken_order_rejected(self):
        r=rows("5m")
        r[3],r[4]=r[4],r[3]
        with self.assertRaises(ValueError):
            parse_candles(r,"5m",int(NOW.timestamp()*1000))
if __name__=="__main__":unittest.main()
