import datetime as dt
import unittest
from src.okx_history_coverage_v1 import collect, verify_page, INST

NOW=dt.datetime(2026,11,26,12,43,tzinfo=dt.timezone.utc)
END=int(NOW.timestamp()*1000)//300000*300000
START=END-300000

def mk(index,ts):
    return {"instId":INST,"tradeId":str(2000-index),"ts":str(ts),
            "side":"buy" if index%2==0 else "sell","sz":"2"}

def pages():
    # 200 consecutive IDs, descending UTC event time; spans the entire
    # most recent CLOSED M5 window with recent trades above the right boundary.
    allrows=[mk(i,END+120000-i*4000) for i in range(200)]
    return [allrows[:100],allrows[100:]]

class OKXHistoryCoverageTests(unittest.TestCase):
    def test_complete_bounded_interval_is_observation_not_signal(self):
        chunks=pages()
        def getter(cursor):
            return chunks[0] if cursor is None else chunks[1] if cursor==1901 else []
        x=collect(getter,NOW,max_pages=3,contract_btc=0.01)
        self.assertEqual(x["status"],"bounded_window_observed")
        self.assertEqual(x["page_count"],2)
        self.assertEqual(x["coverage"],"pagination_crossed_both_m5_window_boundaries")
        self.assertIsNotNone(x["m5_delta_btc"])
        self.assertIsNone(x["m5_cvd"])
        self.assertIsNone(x["trade_signal"])
    def test_page_cap_withholds_delta(self):
        first=pages()[0]
        x=collect(lambda cursor:first,NOW,max_pages=1,contract_btc=0.01)
        self.assertEqual(x["status"],"insufficient_coverage")
        self.assertIsNone(x["m5_delta_btc"])
    def test_duplicates_or_wrong_cursor_rejected(self):
        chunks=pages()
        def getter(cursor):
            return chunks[0] if cursor is None else chunks[0]
        x=collect(getter,NOW,max_pages=2,contract_btc=0.01)
        self.assertEqual(x["status"],"unverified")
        self.assertIsNone(x["m5_delta_btc"])
    def test_unknown_contract_blocks(self):
        with self.assertRaises(ValueError):
            collect(lambda c:[],NOW,contract_btc=None)
    def test_wrong_exchange_rejected(self):
        a=[mk(0,END)]
        a[0]["instId"]="BTC-USDT"
        with self.assertRaises(ValueError):verify_page(a,None,int(NOW.timestamp()*1000))
    def test_bad_order_rejected(self):
        a=[mk(0,END),mk(1,END+1000)]
        with self.assertRaises(ValueError):verify_page(a,None,int(NOW.timestamp()*1000))
    def test_future_events_rejected(self):
        with self.assertRaises(ValueError):
            verify_page([mk(0,int(NOW.timestamp()*1000)+1000)],None,int(NOW.timestamp()*1000))
if __name__=="__main__":unittest.main()
