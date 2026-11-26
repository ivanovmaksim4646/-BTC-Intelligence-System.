"""Spot upper M5 boundary regression tests; no network requests."""
import unittest
from unittest.mock import patch
from src.okx_flow_history_v1 import collect_one, spot_backfill_target, merge
from src.okx_rest_pagination_probe import probe
from src.okx_flow_reconcile import reconcile

END = 1795721400000

def row(i, ts, side="buy"):
    return {"instId":"BTC-USDT", "tradeId":str(i), "ts":str(ts), "side":side, "sz":"0.5"}

class SpotBoundaryTests(unittest.TestCase):
    def collect_cursor(self, instrument):
        seen=[]
        def fake_probe(inst, fetch, end, max_pages):
            fetch(None)
            return {"instrument":inst,"end_ms":end,"volume_reconciled":False}
        def fake_request(path, params):
            if path == "market/history-trades":
                seen.append(params)
            return []
        with patch("src.okx_flow_history_v1.probe", side_effect=fake_probe), \
             patch("src.okx_flow_history_v1.request", side_effect=fake_request), \
             patch("src.okx_flow_history_v1.reconcile", side_effect=lambda r, c, m:r), \
             patch("src.okx_flow_history_v1.time.sleep"):
            collect_one(instrument,END)
        return seen[0]

    def test_nearest_missing_spot_bucket_is_retried(self):
        rows=[{"instrument":"BTC-USDT","end_ms":END-300000,
               "volume_reconciled":True}]
        self.assertEqual(spot_backfill_target(rows,END),END-600000)

    def test_futures_cannot_satisfy_spot_backfill(self):
        rows=[{"instrument":"BTC-USDT-SWAP","end_ms":END-300000,
               "volume_reconciled":True}]
        self.assertEqual(spot_backfill_target(rows,END),END-300000)

    def test_all_48_spot_buckets_present_no_backfill(self):
        rows=[{"instrument":"BTC-USDT","end_ms":END-i*300000,
               "volume_reconciled":True} for i in range(1,49)]
        self.assertIsNone(spot_backfill_target(rows,END))

    def test_backfill_outside_four_hours_is_ignored(self):
        rows=[{"instrument":"BTC-USDT","end_ms":END-i*300000,
               "volume_reconciled":True} for i in range(1,48)]
        self.assertEqual(spot_backfill_target(rows,END),END-48*300000)

    def test_failed_backfill_does_not_enter_history(self):
        rows=merge([], [{"instrument":"BTC-USDT","end_ms":END-300000,
             "start_ms":END-600000,"volume_reconciled":False}],END)
        self.assertEqual(rows,[])

    def test_spot_initial_cursor_extends_beyond_boundary(self):
        p=self.collect_cursor("BTC-USDT")
        self.assertEqual(p["type"],"2")
        self.assertEqual(p["after"],str(END+60000))

    def test_swap_retains_narrow_cursor_and_page_budget(self):
        p=self.collect_cursor("BTC-USDT-SWAP")
        self.assertEqual(p["type"],"2")
        self.assertEqual(p["after"],str(END+1000))

    def test_missing_postclose_trade_still_not_reconciled(self):
        pages=iter([[row(9,END-1000),row(8,END-2000),row(7,END-300000-1)]])
        result=probe("BTC-USDT",lambda _:next(pages),END)
        self.assertFalse(result["both_time_boundaries_observed"])
        candle=[[str(END-300000),"0","0","0","0","1.0","0","0","1"]]
        audited=reconcile(result,candle)
        self.assertFalse(audited["volume_reconciled"])
        self.assertEqual(audited["reconciliation_reason"],"incomplete_boundaries")

    def test_postclose_observation_allows_independent_reconciliation(self):
        pages=iter([[row(9,END+1400),row(8,END-1000),
                      row(7,END-2000,"sell"),row(6,END-300000-1)]])
        result=probe("BTC-USDT",lambda _:next(pages),END)
        self.assertTrue(result["both_time_boundaries_observed"])
        candle=[[str(END-300000),"0","0","0","0","1.0","0","0","1"]]
        audited=reconcile(result,candle)
        self.assertTrue(audited["volume_reconciled"])
        self.assertIsNone(audited["complete_cvd_btc"])

if __name__=="__main__":
    unittest.main()
