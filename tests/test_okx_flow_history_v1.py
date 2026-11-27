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
