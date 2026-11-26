import datetime as dt
import unittest
from src.okx_futures_orderflow_v1 import observe, collect, SYMBOL
NOW=dt.datetime(2026,11,26,12,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)
def fixture():
    trades=[{"instId":SYMBOL,"tradeId":str(i),"ts":str(TS-60000+i*1000),
              "side":"buy" if i%2==0 else "sell","sz":"2"} for i in range(10)]
    start=(TS//300000-24)*300000
    candles=[[str(start+i*300000),"100","102","99","101","123","10","1000","1"]
             for i in range(24)]
    oi=[{"instId":SYMBOL,"oiCcy":"2000","ts":str(TS-5000)}]
    instrument=[{"instId":SYMBOL,"ctValCcy":"BTC","ctVal":"0.01"}]
    return trades,candles,oi,instrument
class OKXTests(unittest.TestCase):
    def test_signed_page_not_full_cvd(self):
        r=observe(*fixture(),now=NOW)
        self.assertEqual(r["status"],"observed_partial_coverage")
        self.assertEqual(r["recent_trades"]["count"],10)
        self.assertEqual(r["recent_trades"]["signed_btc_in_returned_page"],0)
        self.assertIsNone(r["m5_cvd"])
        self.assertIsNone(r["m5_delta_btc"])
        self.assertIsNone(r["open_interest"]["change"])
        self.assertIsNone(r["trade_signal"])
    def test_missing_contract_metadata_blocks_trade_delta(self):
        a=list(fixture());a[3][0]["ctValCcy"]="USDT"
        r=observe(*a,now=NOW)
        self.assertEqual(r["recent_trades"]["status"],"unavailable")
        self.assertIsNone(r["m5_cvd"])
    def test_duplicate_trades_rejected(self):
        a=list(fixture());a[0].append(dict(a[0][0]))
        r=observe(*a,now=NOW)
        self.assertEqual(r["recent_trades"]["status"],"unavailable")
    def test_unclosed_candle_excluded(self):
        a=list(fixture());a[1].append([str(TS),"100","102","99","101","1","1","1","0"])
        r=observe(*a,now=NOW)
        self.assertEqual(r["candles"]["status"],"observed")
    def test_failed_endpoint_not_fake_success(self):
        def blocked(path,params):raise OSError("unavailable")
        r=collect(NOW,blocked)
        self.assertEqual(r["status"],"partial")
        self.assertEqual(len(r["endpoint_errors"]),4)
        self.assertIsNone(r["trade_signal"])
    def test_reversed_candle_invalid(self):
        a=list(fixture());a[1][0][2]="1"
        r=observe(*a,now=NOW)
        self.assertEqual(r["candles"]["status"],"unavailable")
if __name__=="__main__":unittest.main()
