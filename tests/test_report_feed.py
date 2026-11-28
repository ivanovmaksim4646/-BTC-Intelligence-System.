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

    def test_okx_kept_separate_from_legacy_kraken(self):
        okx = {"source": "OKX BTC-USDT-SWAP", "classification": "okx_confluence_research_only",
               "generated_at_utc": STAMP, "m5_close_s": int(NOW.timestamp())-300,
               "missing": ["macro"], "flow": {"5m": {"spot": {"delta_btc": "2"}}}}
        report = build(*fixtures(), now=NOW, okx=okx)
        self.assertEqual(report["okx_confluence"]["status"], "research_partial")
        self.assertEqual(report["order_flow"]["H4"]["spot_delta"], 1.5)
        self.assertIsNone(report["okx_confluence"]["trade_signal"])

    def test_stale_okx_withheld(self):
        okx = {"source": "OKX BTC-USDT-SWAP", "classification": "okx_confluence_research_only",
               "generated_at_utc": "2026-11-26T11:00:00Z", "m5_close_s": int(NOW.timestamp())-3600}
        self.assertIsNone(build(*fixtures(), now=NOW, okx=okx)["okx_confluence"]["data"])


class BackupMarketContextTests(unittest.TestCase):
    def test_closed_binance_windows_and_independent_failure(self):
        from src.report_feed import backup_market_context
        end = int(NOW.timestamp()) // 300 * 300000
        def fetch(url):
            if "bybit" in url:
                raise TimeoutError("fixture")
            return [[t,"1","1","1","1","10",t+299999,"0",1,"6","0"]
                    for t in range(end-48*300000,end+300000,300000)]
        out=backup_market_context(NOW,fetch=fetch)
        self.assertEqual(out["sources"]["Binance Spot BTCUSDT"]["windows"]["H4"]["delta_btc"],96)
        self.assertEqual(out["sources"]["Binance USD-M BTCUSDT"]["windows"]["M5"]["volume_btc"],10)
        self.assertEqual(out["sources"]["Bybit Linear BTCUSDT"]["status"],"unavailable")
        self.assertIsNone(out["trade_signal"])

    def test_binance_missing_bucket_not_full_window(self):
        from src.report_feed import backup_market_context
        end = int(NOW.timestamp()) // 300 * 300000
        def fetch(url):
            if "bybit" in url:
                raise ValueError("fixture")
            return [[end-300000,"1","1","1","1","10",end-1,"0",1,"6","0"]]
        out=backup_market_context(NOW,fetch=fetch)
        self.assertNotIn("M15",out["sources"]["Binance Spot BTCUSDT"]["windows"])
        self.assertIn("M5",out["sources"]["Binance Spot BTCUSDT"]["windows"])
