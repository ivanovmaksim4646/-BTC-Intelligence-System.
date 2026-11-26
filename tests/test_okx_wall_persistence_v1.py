import copy
import datetime as dt
import unittest
from src.okx_wall_persistence_v1 import analyze, matched, MIN_SAMPLES, SOURCE

NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)

def row(ts, bid=100.0, ask=110.0, bidwalls=None, askwalls=None):
    bidwalls=bidwalls if bidwalls is not None else [(99.5,5.0),(98.0,3.0)]
    askwalls=askwalls if askwalls is not None else [(110.5,5.0),(112.0,3.0)]
    return {"source":SOURCE,"book_timestamp_ms":ts,"coverage":"single_cancelable_resting_book_snapshot",
        "trade_signal":None,"best_bid":bid,"best_ask":ask,
        "bid_depth_btc":30.0,"ask_depth_btc":20.0,"imbalance":.2,
        "bid_walls":[{"price":p,"btc":v} for p,v in bidwalls],
        "ask_walls":[{"price":p,"btc":v} for p,v in askwalls]}

def seq():
    return [row(TS-601000),row(TS-301000),row(TS-1000)]

class WallPersistenceTests(unittest.TestCase):
    def test_three_matching_observations(self):
        r=analyze(seq(),NOW)
        self.assertEqual(r["status"],"sampled_comparison_available")
        self.assertEqual(r["samples_considered"],MIN_SAMPLES)
        self.assertEqual(len(r["persistent_bid_zones"]),2)
        self.assertEqual(len(r["persistent_ask_zones"]),2)
        self.assertEqual(r["persistent_bid_zones"][0]["samples_seen"],3)
        self.assertFalse(r["persistent_bid_zones"][0]["intraperiod_persistence_verified"])
        self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["complete_cvd_btc"])
    def test_two_samples_cannot_claim_persistence(self):
        r=analyze(seq()[-2:],NOW)
        self.assertEqual(r["status"],"insufficient_history")
        self.assertFalse(r["persistent_bid_zones"])
    def test_invalid_history_fails_closed(self):
        r=analyze([{"no":"source"}],NOW)
        self.assertEqual(r["status"],"invalid_history")
    def test_stale_last_snapshot_fails_closed(self):
        old=seq()
        for x in old:x["book_timestamp_ms"]-=20*60*1000
        self.assertEqual(analyze(old,NOW)["status"],"stale_history")
    def test_gapped_intervals_not_merged(self):
        xs=seq()
        xs[0]["book_timestamp_ms"]-=30*60*1000
        r=analyze(xs,NOW)
        self.assertEqual(r["status"],"insufficient_history")
        self.assertIn("broken_snapshot_sequence",r["warnings"])
    def test_large_price_move_rejected(self):
        xs=seq();xs[0]["best_bid"]=80;xs[0]["best_ask"]=90
        r=analyze(xs,NOW)
        self.assertEqual(r["status"],"noncomparable_price_regime")
    def test_moving_price_zone_within_tolerance(self):
        xs=seq()
        xs[1]["bid_walls"][0]["price"]=99.504
        xs[2]["bid_walls"][0]["price"]=99.506
        r=analyze(xs,NOW)
        self.assertEqual(len(r["persistent_bid_zones"]),2)
    def test_no_match_when_wall_moves_far(self):
        xs=seq()
        xs[2]["bid_walls"][0]["price"]=95
        r=analyze(xs,NOW)
        self.assertEqual(len(r["persistent_bid_zones"]),1)
        self.assertEqual(r["no_longer_top3_bid_zones"][0]["price"],99.5)
        self.assertIn("not_top3_now",r["no_longer_top3_bid_zones"][0]["interpretation"])
    def test_new_visible_not_claimed_new_orders(self):
        xs=seq()
        xs[2]["ask_walls"][1]["price"]=120
        r=analyze(xs,NOW)
        self.assertEqual(r["newly_visible_ask_zones"][0]["interpretation"],"not_top3_at_prior_sample")
    def test_same_level_not_double_used(self):
        p=[{"price":100.0},{"price":100.002}]
        q=[{"price":100.001}]
        self.assertEqual(len(matched(p,q,100)),1)
    def test_sizes_change_not_inferred_execution(self):
        xs=seq()
        xs[1]["bid_walls"][0]["btc"]=1
        xs[2]["bid_walls"][0]["btc"]=8
        r=analyze(xs,NOW)
        self.assertEqual(r["persistent_bid_zones"][0]["max_observed_btc"],8)
        self.assertIsNone(r["confirmed_absorption"])
        self.assertIsNone(r["confirmed_spoofing"])
    def test_out_of_order_history_normalizes_by_exchange_ts(self):
        xs=seq()
        r=analyze(xs[::-1],NOW)
        self.assertEqual(r["status"],"sampled_comparison_available")
    def test_oldest_snapshot_can_be_more_than_15min_if_last_fresh_and_gaps_valid(self):
        xs=[row(TS-901000),row(TS-601000),row(TS-301000),row(TS-1000)]
        r=analyze(xs,NOW)
        self.assertEqual(r["status"],"sampled_comparison_available")
        self.assertEqual(r["samples_considered"],4)
    def test_history_does_not_exceed_last_twelve(self):
        xs=[row(TS-300000*i-1000) for i in reversed(range(20))]
        r=analyze(xs,NOW)
        self.assertEqual(r["samples_considered"],12)
    def test_no_liquidation_or_trade_signal_even_if_bid_dominance(self):
        xs=seq()
        for x in xs:
            x["bid_depth_btc"]=1000.0;x["ask_depth_btc"]=1.0;x["imbalance"]=.998
        r=analyze(xs,NOW)
        self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["liquidation_heatmap"])
        self.assertFalse(r["entry_signal"])
if __name__=="__main__":unittest.main()
