import unittest
from src.okx_flow_history_v1 import merge,summarize
def row(t,inst="BTC-USDT",delta="1"):
    return {"instrument":inst,"end_ms":t,"start_ms":t-300000,"volume_reconciled":True,"delta_btc_reconciled":delta,"volume_btc_reconciled":"2"}
class FlowHistoryTests(unittest.TestCase):
    def test_gap_resets_segment(self):
        rows=merge([], [row(300000),row(900000)],900000)
        s=summarize(rows,900000)["BTC-USDT"]
        self.assertEqual(s["consecutive_m5"],1)
        self.assertIsNone(s["rolling_windows"]["15m"]["delta_btc_reconciled"])
    def test_merge_idempotent(self):
        r=row(300000)
        self.assertEqual(len(merge([r],[dict(r,elapsed_seconds=2)],300000)),1)
    def test_conflict(self):
        with self.assertRaises(ValueError):merge([row(300000)],[row(300000,delta="2")],300000)
    def test_market_separation(self):
        rows=merge([], [row(300000),row(300000,"BTC-USDT-SWAP",delta="-1")],300000)
        s=summarize(rows,300000)
        self.assertEqual(s["BTC-USDT"]["segment_cvd_btc_reconciled"],"1")
        self.assertEqual(s["BTC-USDT-SWAP"]["segment_cvd_btc_reconciled"],"-1")
    def test_ignore_unverified(self):
        self.assertEqual(merge([],[dict(row(300000),volume_reconciled=False)],300000),[])

    def test_futures_backfill_separate_and_excludes_current(self):
        from src.okx_flow_history_v1 import backfill_target
        end=1200000
        rows=[row(900000),row(600000,"BTC-USDT-SWAP")]
        self.assertEqual(backfill_target(rows,end,instrument="BTC-USDT-SWAP"),900000)
        self.assertEqual(backfill_target(rows,end),600000)

    def test_rotate_failed_gap(self):
        from src.okx_flow_history_v1 import rotating_backfill_target
        end=15000000
        rows=[row(end-600000)]
        self.assertEqual(rotating_backfill_target(rows,end,"BTC-USDT",end-300000),end-900000)

    def test_rotation_only_within_h4(self):
        from src.okx_flow_history_v1 import rotating_backfill_target
        end=15000000
        rows=[row(end-i*300000) for i in range(1,48)]
        self.assertIsNone(rotating_backfill_target(rows,end,"BTC-USDT"))

    def test_rotation_instrument_isolation(self):
        from src.okx_flow_history_v1 import rotating_backfill_target
        end=15000000
        self.assertEqual(rotating_backfill_target([row(end-300000)],end,"BTC-USDT-SWAP"),end-300000)

class SplitRepairTests(unittest.TestCase):
    instrument="BTC-USDT-SWAP"
    def observations(self):
        # Two trades sharing a boundary timestamp, two empty minutes and
        # independent real trades just outside the M5 candle.
        ticks=[(-1,"buy"),(1000,"buy"),(59999,"sell"),(180000,"buy"),
               (180000,"sell"),(285000,"sell"),(300005,"buy")]
        return [dict(tradeId=str(i+1),ts=str(t),instId=self.instrument,side=side,sz="0.1")
                for i,(t,side) in enumerate(ticks)]
    def parts(self):
        from src.okx_rest_pagination_probe import probe
        rows=self.observations()[::-1]
        return [probe(self.instrument,lambda cursor:rows,t,1,span_ms=60000)
                for t in range(60000,300001,60000)]
    def test_split_matches_serial_with_empty_minutes_and_tied_timestamp(self):
        from src.okx_flow_history_v1 import join_minutes
        from src.okx_rest_pagination_probe import probe
        rows=self.observations()[::-1]
        serial=probe(self.instrument,lambda cursor:rows,300000,1)
        split=join_minutes(self.parts(),300000)
        for k in ("both_time_boundaries_observed","in_window_trades","observed_buy_native","observed_sell_native","observed_delta_native"):
            self.assertEqual(split[k],serial[k],k)
        self.assertTrue(split["both_time_boundaries_observed"])
        self.assertIsNone(split["complete_cvd_btc"])
    def test_disagreement_between_pages_blocks_reconciliation(self):
        from src.okx_flow_history_v1 import join_minutes
        from src.okx_flow_reconcile import reconcile
        parts=self.parts()
        parts[2]["upper_outside"]=(999,180000,"sell","0.1")
        r=join_minutes(parts,300000)
        self.assertFalse(r["both_time_boundaries_observed"])
        self.assertFalse(reconcile(r,[])["volume_reconciled"])
    def test_missing_minute_is_rejected(self):
        from src.okx_flow_history_v1 import join_minutes
        with self.assertRaises(ValueError):join_minutes(self.parts()[:-1],300000)
