import datetime as dt
import unittest
from src.okx_flow_coverage_v1 import evaluate, normalize_history, VENUE
NOW=dt.datetime(2026,11,26,14,0,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp()*1000)
def snap(ts=TS-1000,oi=32000.0):
    return {"source":VENUE,"collected_at_utc":NOW.isoformat(),
       "recent_trades":{"status":"observed","coverage":"limited_page_not_full_window",
          "count":500,"earliest_ts_ms":TS-26000,"latest_ts_ms":TS-1000,
          "ctVal_btc_per_contract":0.01,"signed_btc_in_returned_page":3.25},
       "open_interest":{"status":"snapshot_only","value_btc_reported":oi,
                         "timestamp_ms":ts}}
def record(t,oi):
    return {"source":VENUE,"timestamp_ms":t,"oi_btc":oi}

class OKXFlowCoverageTests(unittest.TestCase):
    def test_partial_trade_page_never_complete_m5_or_cvd(self):
        r,h=evaluate(snap(),[],NOW)
        self.assertEqual(r["status"],"sampled_only")
        self.assertEqual(r["sampled_rest_page"]["signed_btc_in_page"],3.25)
        self.assertEqual(r["sampled_rest_page"]["coverage"],"NOT_A_FULL_WINDOW")
        self.assertIsNone(r["complete_m5_delta_btc"])
        self.assertIsNone(r["complete_cvd_btc"])
        for tf in ("5m","15m","1h","4h"):
            self.assertFalse(r["coverage_by_window"][tf]["full_coverage_verified"])
            self.assertIsNone(r["coverage_by_window"][tf]["delta_btc"])
            self.assertIsNone(r["coverage_by_window"][tf]["cvd_btc"])
    def test_oi_change_derived_from_two_real_distinct_snapshots(self):
        previous=record(TS-301000,31800)
        r,h=evaluate(snap(),[previous],NOW)
        self.assertEqual(r["oi_change"]["delta_btc"],200)
        self.assertEqual(r["oi_change"]["elapsed_seconds"],300)
        self.assertEqual(len(h),2)
        self.assertEqual(r["oi_change"]["status"],"two_verified_snapshots")
    def test_duplicate_oi_snapshot_never_double_counted(self):
        cur=record(TS-1000,32000)
        r,h=evaluate(snap(),[cur],NOW)
        self.assertIsNone(r["oi_change"])
        self.assertEqual(h,[cur])
        self.assertIn("duplicate_oi_snapshot",r["warnings"])
    def test_conflicting_oi_snapshot_never_overwrites(self):
        cur=record(TS-1000,31000)
        r,h=evaluate(snap(),[cur],NOW)
        self.assertEqual(h,[cur])
        self.assertIn("conflicting_oi_snapshot",r["warnings"])
    def test_gap_more_than_twenty_minutes_censors_oi_change(self):
        prev=record(TS-1300000,31800)
        r,h=evaluate(snap(),[prev],NOW)
        self.assertIsNone(r["oi_change"])
        self.assertIn("oi_snapshot_gap_too_large",r["warnings"])
    def test_stale_snapshot_discarded(self):
        x=snap()
        x["collected_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        r,h=evaluate(x,[],NOW)
        self.assertEqual(r["status"],"unavailable")
        self.assertIn("stale_orderflow_snapshot",r["warnings"])
        self.assertEqual(h,[])
    def test_cross_venue_never_used(self):
        x=snap();x["source"]="BingX"
        r,h=evaluate(x,[],NOW)
        self.assertEqual(r["status"],"unavailable")
        self.assertEqual(h,[])
    def test_oi_missing_still_research_page_not_trade(self):
        x=snap();x["open_interest"]=None
        r,h=evaluate(x,[],NOW)
        self.assertEqual(r["status"],"sampled_only")
        self.assertIsNone(r["oi_change"])
        self.assertIsNone(r["trade_signal"])
    def test_corrupt_history_fail_closed(self):
        for bad in ([{"source":VENUE,"timestamp_ms":TS,"oi_btc":-3}],
                    [record(TS-5000,10),record(TS-5000,20)]):
            with self.assertRaises(ValueError):
                normalize_history(bad)
            r,h=evaluate(snap(),bad,NOW)
            self.assertEqual(h,[])
            self.assertEqual(r["status"],"unavailable")
    def test_out_of_order_new_oi_not_appended(self):
        r,h=evaluate(snap(ts=TS-1000),[record(TS+1000,31111)],NOW)
        self.assertIn("out_of_order_oi_snapshot",r["warnings"])
        self.assertEqual(len(h),1)
    def test_sampled_interval_does_not_cover_m5_despite_frequent_cron(self):
        x=snap()
        x["recent_trades"]["earliest_ts_ms"]=TS-310000
        # A long page still does not establish missing trade-free continuity.
        r,h=evaluate(x,[],NOW)
        self.assertFalse(r["coverage_by_window"]["5m"]["full_coverage_verified"])
    def test_incomplete_exchange_page_cannot_be_upgraded_by_malicious_flag(self):
        x=snap()
        x["recent_trades"]["coverage"]="complete"
        r,h=evaluate(x,[],NOW)
        self.assertIsNone(r["sampled_rest_page"])
        self.assertEqual(r["status"],"unavailable")
if __name__=="__main__":unittest.main()
