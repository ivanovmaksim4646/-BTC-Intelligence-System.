import unittest
from src.okx_flow_reconcile import reconcile,aggregate
def row(end=300000,inst="BTC-USDT"):
    return {"instrument":inst,"start_ms":end-300000,"end_ms":end,"both_time_boundaries_observed":True,"observed_buy_native":"2","observed_sell_native":"1"}
def candle(start=0,vol="3",confirmed="1"):
    return [str(start),"1","1","1","1",vol,"0","0",confirmed]
class ReconcileTests(unittest.TestCase):
    def test_exact(self):
        r=reconcile(row(),[candle()])
        self.assertTrue(r["volume_reconciled"])
        self.assertEqual(r["delta_btc_reconciled"],"1")
    def test_mismatch(self):
        self.assertFalse(reconcile(row(),[candle(vol="4")])["volume_reconciled"])
    def test_forming(self):
        self.assertFalse(reconcile(row(),[candle(confirmed="0")])["volume_reconciled"])
    def test_swap(self):
        r=reconcile(row(inst="BTC-USDT-SWAP"),[candle()],[{"instId":"BTC-USDT-SWAP","ctValCcy":"BTC","ctType":"linear","ctVal":"0.01"}])
        self.assertEqual(r["delta_btc_reconciled"],"0.01")
    def test_gap(self):
        rows=[reconcile(row(t),[candle(t-300000)]) for t in (300000,900000)]
        self.assertIsNone(aggregate(rows,900000,"BTC-USDT")["15m"]["delta_btc_reconciled"])
    def test_all_windows(self):
        rows=[reconcile(row(t),[candle(t-300000)]) for t in range(300000,14400001,300000)]
        a=aggregate(rows,14400000,"BTC-USDT")
        self.assertEqual([a[x]["delta_btc_reconciled"] for x in ("5m","15m","1h","4h")],["1","3","12","48"])
        self.assertIsNone(a["4h"]["complete_cvd_btc"])
    def test_conflict(self):
        r=reconcile(row(),[candle()])
        with self.assertRaises(ValueError):aggregate([r,dict(r,delta_btc_reconciled="2")],300000,"BTC-USDT")
