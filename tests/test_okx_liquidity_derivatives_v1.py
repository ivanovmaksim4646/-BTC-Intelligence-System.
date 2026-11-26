import datetime as dt
import unittest
from src.okx_liquidity_derivatives_v1 import evaluate, VENUE
NOW=dt.datetime(2026,11,26,14,30,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)
def fixture():
    return dict(
      book=[{"ts":str(TS-1000),"bids":[["60000","10","0","1"],["59999","20","0","1"]],
                  "asks":[["60001","5","0","1"],["60002","15","0","1"]]}],
      funding=[{"instId":"BTC-USDT-SWAP","fundingRate":"0.0001",
                "nextFundingTime":str(TS+3600000)}],
      mark=[{"instId":"BTC-USDT-SWAP","markPx":"60000","ts":str(TS-2000)}],
      index=[{"instId":"BTC-USDT","idxPx":"59980","ts":str(TS-3000)}],
      instruments=[{"instId":"BTC-USDT-SWAP","ctVal":"0.01","ctValCcy":"BTC"}])
class OKXLiquidityDerivativesTests(unittest.TestCase):
    def test_valid_same_venue_snapshot(self):
        r=evaluate(**fixture(),now=NOW)
        b=r["book"]
        self.assertEqual(b["status"],"snapshot_only")
        self.assertAlmostEqual(b["bid_depth_btc"],0.3)
        self.assertAlmostEqual(b["ask_depth_btc"],0.2)
        self.assertEqual(b["bid_walls"][0]["price"],59999)
        self.assertAlmostEqual(b["resting_imbalance"],0.2)
        self.assertEqual(r["funding"]["rate_percent"],0.01)
        self.assertAlmostEqual(r["mark_index"]["premium_bps"],10000*20/59980,places=5)
        self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["liquidation_heatmap"])
        self.assertIsNone(r["complete_cvd_btc"])
    def test_reject_crossed_book(self):
        x=fixture();x["book"][0]["asks"][0][0]="60000"
        r=evaluate(**x,now=NOW)
        self.assertEqual(r["book"]["status"],"unavailable")
        self.assertIn("crossed_book",r["warnings"])
    def test_reject_unordered_book(self):
        x=fixture();x["book"][0]["bids"][1][0]="60001"
        self.assertEqual(evaluate(**x,now=NOW)["book"]["status"],"unavailable")
    def test_reject_duplicate_prices(self):
        x=fixture();x["book"][0]["asks"][1][0]="60001"
        self.assertEqual(evaluate(**x,now=NOW)["book"]["status"],"unavailable")
    def test_stale_book_not_reported(self):
        x=fixture();x["book"][0]["ts"]=str(TS-500000)
        self.assertEqual(evaluate(**x,now=NOW)["book"]["status"],"unavailable")
    def test_missing_contract_multiplier_no_fake_btc(self):
        x=fixture();x["instruments"][0]["ctValCcy"]="USDT"
        r=evaluate(**x,now=NOW)
        self.assertEqual(r["book"]["status"],"unavailable")
        self.assertIn("instrument_ctval_btc_unverified",r["warnings"])
    def test_missing_side_no_book(self):
        x=fixture();x["book"][0]["asks"]=[]
        self.assertEqual(evaluate(**x,now=NOW)["book"]["status"],"unavailable")
    def test_funding_negative_allowed_but_unreasonable_rejected(self):
        x=fixture();x["funding"][0]["fundingRate"]="-0.0002"
        self.assertEqual(evaluate(**x,now=NOW)["funding"]["rate_percent"],-0.02)
        x["funding"][0]["fundingRate"]="500"
        self.assertEqual(evaluate(**x,now=NOW)["funding"]["status"],"unavailable")
    def test_index_mismatched_symbol_not_used(self):
        x=fixture();x["index"][0]["instId"]="ETH-USDT"
        self.assertEqual(evaluate(**x,now=NOW)["mark_index"]["status"],"unavailable")
    def test_stale_mark_or_index_rejected(self):
        x=fixture();x["mark"][0]["ts"]=str(TS-500000)
        self.assertEqual(evaluate(**x,now=NOW)["mark_index"]["status"],"unavailable")
    def test_unknown_orderbook_zero_size_rejected(self):
        x=fixture();x["book"][0]["bids"][0][1]="0"
        self.assertEqual(evaluate(**x,now=NOW)["book"]["status"],"unavailable")
    def test_missing_all_venues_no_trade(self):
        r=evaluate([],[],[],[],[],NOW)
        self.assertEqual(r["status"],"unavailable")
        self.assertIsNone(r["trade_signal"])
if __name__=="__main__":unittest.main()
