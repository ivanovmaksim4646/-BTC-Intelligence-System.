import datetime as dt
import unittest
from src.okx_liquidity_history_v1 import analyze, compare, create_observation, normalize, SOURCE
NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)
def sample(ts=TS-1000,bid=10.0,ask=20.0,funding=0.0001,premium=2.0):
    return {"source":SOURCE,"classification":"public_rest_snapshot_research_only",
       "generated_at_utc":NOW.isoformat(),
       "book":{"status":"snapshot_only","timestamp_ms":ts,
           "best_bid":60000.0,"best_ask":60001.0,
           "bid_depth_btc":bid,"ask_depth_btc":ask,
           "bid_walls":[{"price":59999.0,"btc":5.0,"contracts":500.0,"notional_usdt":299995.0}],
           "ask_walls":[{"price":60002.0,"btc":8.0,"contracts":800.0,"notional_usdt":480016.0}]},
       "funding":{"status":"quoted_rate_snapshot","rate_fraction":funding,
                  "next_funding_time_ms":TS+3600000},
       "mark_index":{"status":"two_recent_public_snapshots",
           "mark_price":60000.0+premium*60000.0/10000,
           "index_price":60000.0,"mark_timestamp_ms":ts,"index_timestamp_ms":ts}}
class LiquidityHistoryTests(unittest.TestCase):
    def test_initial_record_kept_without_invented_change(self):
        r,h=analyze(sample(),[],NOW)
        self.assertTrue(r["new_record"]);self.assertEqual(r["saved_count"],1)
        self.assertIsNone(r["change"]);self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["complete_cvd_btc"])
    def test_two_samples_produce_changes_not_executions(self):
        older=create_observation(sample(ts=TS-302000,bid=7.0,ask=24.0,premium=3.0),NOW)
        r,h=analyze(sample(bid=10,ask=20,premium=2.0),[older],NOW)
        self.assertTrue(r["new_record"])
        self.assertEqual(len(h),2)
        d=r["change"]
        self.assertEqual(d["status"],"two_sample_change_only")
        self.assertEqual(d["bid_depth_change_btc"],3.0)
        self.assertEqual(d["ask_depth_change_btc"],-4.0)
        self.assertAlmostEqual(d["premium_change_bps"],-1.0,places=3)
        self.assertFalse(d["interval_fully_observed"])
    def test_long_gap_censored(self):
        old=create_observation(sample(ts=TS-3601000),NOW) if False else create_observation(sample(),NOW)
        old["book_timestamp_ms"]=TS-3601000
        r,h=analyze(sample(),[old],NOW)
        self.assertTrue(r["new_record"])
        self.assertEqual(r["change"]["reason"],"snapshot_gap_over_20m")
    def test_duplicate_book_timestamp_is_idempotent(self):
        row=create_observation(sample(),NOW)
        r,h=analyze(sample(),[row],NOW)
        self.assertFalse(r["new_record"]);self.assertEqual(h,[row])
        self.assertIn("duplicate_timestamp_no_append",r["warnings"])
    def test_conflicting_same_time_never_overwrites(self):
        row=create_observation(sample(bid=5),NOW)
        r,h=analyze(sample(bid=10),[row],NOW)
        self.assertFalse(r["new_record"])
        self.assertIn("same_timestamp_conflicting_snapshot",r["warnings"])
        self.assertEqual(h,[row])
    def test_out_of_order_never_appends(self):
        newer=create_observation(sample(),NOW)
        older=sample(ts=TS-2000)
        r,h=analyze(older,[newer],NOW)
        self.assertIn("out_of_order_snapshot_no_append",r["warnings"])
        self.assertFalse(r["new_record"])
    def test_stale_snapshot_discarded(self):
        x=sample();x["generated_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        r,h=analyze(x,[],NOW)
        self.assertFalse(r["new_record"])
        self.assertIn("stale_snapshot",r["warnings"])
    def test_missing_book_not_saved(self):
        x=sample();x["book"]["status"]="unavailable"
        r,h=analyze(x,[],NOW)
        self.assertFalse(r["new_record"])
        self.assertIn("missing_verified_book",r["warnings"])
    def test_cross_venue_not_saved(self):
        x=sample();x["source"]="BingX USD-M Perpetual BTC-USDT"
        r,h=analyze(x,[],NOW)
        self.assertIn("unverified_source",r["warnings"])
    def test_bad_future_funding_is_omitted_not_fabricated(self):
        x=sample();x["funding"]["next_funding_time_ms"]=TS-20
        row=create_observation(x,NOW)
        self.assertIsNone(row["funding_rate_fraction"])
    def test_premium_old_omitted(self):
        x=sample();x["mark_index"]["mark_timestamp_ms"]=TS-600000
        row=create_observation(x,NOW)
        self.assertIsNone(row["premium_bps"])
    def test_corrupt_history_fail_closed(self):
        x=sample();bad=[{"source":SOURCE,"book_timestamp_ms":TS}]
        r,h=analyze(x,bad,NOW)
        self.assertIsNone(h)
        self.assertIn("corrupt_liquidity_history",r["warnings"])
    def test_history_duplicate_conflict(self):
        row=create_observation(sample(),NOW)
        changed=dict(row,bid_depth_btc=100)
        with self.assertRaisesRegex(ValueError,"conflicting_history_timestamp"):
            normalize([row,changed])
    def test_imbalance_not_directional_trade_signal(self):
        r,h=analyze(sample(bid=100,ask=1),[],NOW)
        self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["liquidation_heatmap"])
        self.assertEqual(h[0]["coverage"],"single_cancelable_resting_book_snapshot")
    def test_persisted_history_retention(self):
        row=create_observation(sample(),NOW)
        rows=[dict(row,book_timestamp_ms=TS-2500*300000+i*300000) for i in range(2500)]
        r,h=analyze(sample(),rows,NOW)
        self.assertTrue(r["new_record"])
        self.assertEqual(len(h),2500)
if __name__=="__main__":unittest.main()
