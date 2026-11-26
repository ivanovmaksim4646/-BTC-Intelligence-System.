import copy
import datetime as dt
import unittest
from src.okx_liquidity_intelligence_v1 import evaluate, SOURCE
NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)
ISO=NOW.isoformat()
def fixtures():
    context={"source":SOURCE,"classification":"read_only_okx_snapshot_context",
      "generated_at_utc":ISO,
      "book":{"status":"snapshot_only","timestamp_ms":TS-1000,
         "bid_depth_btc":15.0,"ask_depth_btc":8.0,
         "best_bid":60000.0,"best_ask":60000.1,"resting_imbalance":.304347},
      "funding":{"status":"quoted_rate_snapshot",
          "rate_fraction":.00005,"next_funding_time_ms":TS+3600000},
      "mark_index":{"status":"two_recent_public_snapshots",
          "mark_price":59990.0,"index_price":60000.0,
          "mark_timestamp_ms":TS-2000,"index_timestamp_ms":TS-2100}}
    history={"source":SOURCE,"classification":"historical_resting_liquidity_sampling_only",
      "generated_at_utc":ISO,"latest":{"source":SOURCE,"book_timestamp_ms":TS-1000},
      "change":{"status":"two_sample_change_only","interval_fully_observed":False,
           "elapsed_seconds":300,"bid_depth_change_btc":5.0,
           "ask_depth_change_btc":-3.0,"imbalance_change":.2}}
    zone={"last_price":59999.5,"last_observed_btc":5.0,
      "samples_seen":3,"intraperiod_persistence_verified":False}
    wall={"source":SOURCE,"classification":"sampled_top3_resting_price_zone_persistence_only",
       "generated_at_utc":ISO,"status":"sampled_comparison_available",
       "gaps_verified_continuous":False,"sample_last_ms":TS-1000,
       "samples_considered":3,"persistent_bid_zones":[zone],
       "persistent_ask_zones":[]}
    flow={"source":SOURCE,"classification":"partial_rest_flow_audit_only",
       "generated_at_utc":ISO,
       "oi_snapshot":{"timestamp_ms":TS-1500,"oi_btc":32000.0},
       "oi_change":{"status":"two_verified_snapshots",
         "current_timestamp_ms":TS-1500,"delta_btc":-12.0,
         "delta_percent":-.04,"elapsed_seconds":300,
         "limitation":"not_continuous_intraperiod_OI"}}
    return context,history,wall,flow

class LiquidityIntelligenceTests(unittest.TestCase):
    def test_all_six_valid_snapshots_descriptive_only(self):
        r=evaluate(*fixtures(),NOW)
        self.assertEqual(r["status"],"multi_source_observational_context")
        self.assertEqual(sum(v is not None for v in r["observations"].values()),6)
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertFalse(r["execution_ready"])
        self.assertIsNone(r["trade_signal"])
        self.assertIsNone(r["complete_cvd_btc"])
        self.assertIsNone(r["confirmed_absorption"])
        self.assertIsNone(r["liquidation_heatmap"])
    def test_wall_zone_without_interval_presence_cannot_trigger_signal(self):
        r=evaluate(*fixtures(),NOW)
        self.assertFalse(r["observations"]["wall_persistence"]["intraperiod_persistence_verified"])
        self.assertIsNone(r["trade_entry"])
    def test_oi_mismatched_exchange_timestamps_rejected(self):
        a=list(fixtures());a[3]["oi_change"]["current_timestamp_ms"]=TS-500000
        r=evaluate(*a,NOW)
        self.assertIsNone(r["observations"]["open_interest_change"])
        self.assertIn("oi_change_missing_or_misaligned",r["warnings"])
    def test_future_or_invalid_oi_change_not_reported(self):
        a=list(fixtures());a[3]["oi_change"]["delta_btc"]=float("nan")
        self.assertIsNone(evaluate(*a,NOW)["observations"]["open_interest_change"])
    def test_oi_window_above_twenty_minutes_not_reported(self):
        a=list(fixtures());a[3]["oi_change"]["elapsed_seconds"]=1250
        self.assertIsNone(evaluate(*a,NOW)["observations"]["open_interest_change"])
    def test_stale_derivatives_context_fail_closed(self):
        a=list(fixtures());a[0]["generated_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        r=evaluate(*a,NOW)
        self.assertEqual(r["status"],"insufficient_evidence")
        self.assertTrue(all(v is None for v in r["observations"].values()))
    def test_bingx_context_rejected(self):
        a=list(fixtures());a[0]["source"]="BingX"
        self.assertEqual(evaluate(*a,NOW)["status"],"insufficient_evidence")
    def test_stale_book_fail_closed(self):
        a=list(fixtures());a[0]["book"]["timestamp_ms"]=TS-950000
        r=evaluate(*a,NOW)
        self.assertEqual(r["status"],"insufficient_evidence")
        self.assertIsNone(r["observations"]["book"])
    def test_crossed_book_rejected(self):
        a=list(fixtures());a[0]["book"]["best_bid"]=60001
        self.assertIsNone(evaluate(*a,NOW)["observations"]["book"])
    def test_missing_sources_degrade_partial_not_faked(self):
        a=list(fixtures());a[1]={};a[2]={};a[3]={}
        r=evaluate(*a,NOW)
        self.assertEqual(r["status"],"partial_observations")
        self.assertIsNone(r["observations"]["open_interest_change"])
        self.assertIsNone(r["observations"]["wall_persistence"])
    def test_no_wall_persistence_but_valid_empty_zone_lists(self):
        a=list(fixtures());a[2]["persistent_bid_zones"]=[]
        r=evaluate(*a,NOW)
        self.assertEqual(r["observations"]["wall_persistence"]["bid_zones"],0)
    def test_wall_sample_last_mismatch_rejected(self):
        a=list(fixtures());a[2]["sample_last_ms"]=TS-500000
        self.assertIsNone(evaluate(*a,NOW)["observations"]["wall_persistence"])
    def test_fake_intraperiod_wall_continuity_rejected(self):
        a=list(fixtures());a[2]["gaps_verified_continuous"]=True
        self.assertIsNone(evaluate(*a,NOW)["observations"]["wall_persistence"])
    def test_wall_size_unverified_rejected(self):
        a=list(fixtures());a[2]["persistent_bid_zones"][0]["last_observed_btc"]=0
        self.assertIsNone(evaluate(*a,NOW)["observations"]["wall_persistence"])
    def test_mark_index_exchange_ts_mismatch_rejected(self):
        a=list(fixtures());a[0]["mark_index"]["mark_timestamp_ms"]=TS-180000
        self.assertIsNone(evaluate(*a,NOW)["observations"]["mark_index_premium"])
    def test_funding_expired_not_reported(self):
        a=list(fixtures());a[0]["funding"]["next_funding_time_ms"]=TS-1
        self.assertIsNone(evaluate(*a,NOW)["observations"]["funding"])
    def test_negative_funding_is_valid_signed_rate(self):
        a=list(fixtures());a[0]["funding"]["rate_fraction"]=-.0002
        r=evaluate(*a,NOW)
        self.assertEqual(r["observations"]["funding"]["rate_fraction"],-.0002)
    def test_non_synced_history_rejected(self):
        a=list(fixtures());a[1]["latest"]["book_timestamp_ms"]=TS-90000
        self.assertIsNone(evaluate(*a,NOW)["observations"]["depth_change"])
    def test_history_full_coverage_claim_rejected(self):
        a=list(fixtures());a[1]["change"]["interval_fully_observed"]=True
        self.assertIsNone(evaluate(*a,NOW)["observations"]["depth_change"])
    def test_source_age_must_be_utc_aware(self):
        a=list(fixtures());a[3]["generated_at_utc"]="2026-11-26T15:00:00"
        self.assertIsNone(evaluate(*a,NOW)["observations"]["open_interest_change"])
if __name__=="__main__":unittest.main()
