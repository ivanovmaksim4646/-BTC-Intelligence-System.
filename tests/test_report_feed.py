import datetime as dt
import unittest

from src.report_feed import build

NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)
STAMP = "2026-11-26T11:59:00Z"


def fixtures(stamp=STAMP):
    flow = {tf: {"delta": 1.5, "total_volume": 10.0, "coverage": "complete"}
            for tf in ("M5", "M15", "H1", "H4")}
    current = {
        "collected_at_utc": stamp, "status": "verified",
        "order_flow": {"spot": flow, "futures": flow},
        "derivatives": {"open_interest": {"value": 100}},
    }
    analysis = {"data_collected_at_utc": stamp, "fresh": True,
                "timeframes": {"H4": {"observation": "both_aggressive_buy",
                                       "window_end_utc": "2026-11-26T08:00:00Z"}}}
    structure = {"collected_at_utc": stamp, "timeframes": {}}
    watchlist = {"evaluated_at_utc": stamp, "timeframes": {}}
    scheduler = {"source": "cloudflare", "event": "workflow_dispatch"}
    return current, analysis, structure, watchlist, scheduler


class ReportFeedTests(unittest.TestCase):
    def test_ready_when_complete_and_synchronized(self):
        report = build(*fixtures(), now=NOW)
        self.assertEqual(report["report_data_status"], "ready")
        self.assertEqual(report["order_flow"]["H4"]["spot_delta"], 1.5)
        self.assertIsNone(report["trade_signal"])

    def test_stale_data_withheld_even_if_internal_fresh_flag_true(self):
        args = fixtures("2026-11-26T11:00:00Z")
        report = build(*args, now=NOW)
        self.assertEqual(report["report_data_status"], "withhold_or_qualify")
        self.assertIn("stale_or_missing_collection", report["reasons"])

    def test_partial_h4_not_reported_as_confirmed_delta(self):
        current, analysis, structure, watchlist, scheduler = fixtures()
        current["status"] = "partial"
        current["order_flow"]["spot"]["H4"] = {
            "delta": 500, "total_volume": 400, "coverage": "partial"}
        report = build(current, analysis, structure, watchlist, scheduler, now=NOW)
        self.assertIsNone(report["order_flow"]["H4"]["spot_delta"])
        self.assertIn("incomplete_spot_or_futures_coverage", report["reasons"])

    def test_mismatched_analysis_time_rejected(self):
        current, analysis, structure, watchlist, scheduler = fixtures()
        analysis["data_collected_at_utc"] = "2026-11-26T11:30:00Z"
        report = build(current, analysis, structure, watchlist, scheduler, now=NOW)
        self.assertIn("order_flow_not_synchronized", report["reasons"])

    def test_missing_data_does_not_crash_or_claim_ready(self):
        report = build(None, None, None, None, None, now=NOW)
        self.assertEqual(report["report_data_status"], "withhold_or_qualify")
        self.assertIsNone(report["order_flow"]["M5"]["spot_delta"])
