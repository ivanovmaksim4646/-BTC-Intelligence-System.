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


class LiquidationAndHistoryFeedTests(unittest.TestCase):
    def test_liquidation_direction_no_total_claim(self):
        from src.report_feed import bitget_liquidation_sample
        row={"symbol":"BTCUSDT","side":"buy","price":"60000","amount":"0.5",
             "ts":str(int(NOW.timestamp()*1000)-1000)}
        result=bitget_liquidation_sample(NOW,lambda url:{"code":"00000","data":{"list":[row]}})
        self.assertEqual(result["records"][0]["position_direction"],"LONG")
        self.assertFalse(result["complete_coverage"])
        self.assertIsNone(result["amount_unit"])

    def test_liquidation_invalid_symbol_withheld(self):
        from src.report_feed import bitget_liquidation_sample
        row={"symbol":"ETHUSDT","side":"buy","price":"60000","amount":"0.5",
             "ts":str(int(NOW.timestamp()*1000)-1000)}
        result=bitget_liquidation_sample(NOW,lambda url:{"code":"00000","data":{"list":[row]}})
        self.assertEqual(result["status"],"unavailable")

    def test_history_excludes_conflicting_samples(self):
        import json
        from src.report_feed import liquidity_history_chart
        row={"source":"OKX BTC-USDT-SWAP","coverage":"single_cancelable_resting_book_snapshot",
             "book_timestamp_ms":int(NOW.timestamp()*1000)-1000,
             "bid_walls":[{"price":59999,"btc":1}],"ask_walls":[{"price":60000,"btc":2}]}
        other=dict(row,bid_walls=[{"price":59999,"btc":3}])
        result=liquidity_history_chart(NOW,[json.dumps(row),json.dumps(other)])
        self.assertEqual(result["excluded_conflicts"],1)
        self.assertFalse(result["samples"])


class FuturesBackupAndChartTests(unittest.TestCase):
    def test_select_independent_kraken_when_okx_missing(self):
        from src.report_feed import futures_report_sources
        end=NOW.isoformat()
        start=(NOW-dt.timedelta(minutes=5)).isoformat()
        current={"collected_at_utc":STAMP,"order_flow":{"futures":{"M5":{
            "delta":2,"total_volume":10,"coverage":"complete","unit":"BTC-equivalent contracts",
            "window_start_utc":start,"window_end_utc":end}}}}
        out=futures_report_sources(current,None,NOW)
        self.assertEqual(out["windows"]["M5"]["preferred"],"Kraken")
        self.assertIsNone(out["windows"]["M15"]["preferred"])
        self.assertIsNone(out["trade_signal"])

    def test_okx_incomplete_window_not_selected(self):
        from src.report_feed import futures_report_sources
        end=int(NOW.timestamp())*1000
        row={"delta_btc_reconciled":"2","volume_btc_reconciled":"10",
             "coverage":"volume_reconciled_not_sequence_certified","end_ms":end,
             "start_ms":end-900000,"required_m5":3,"reconciled_m5":2}
        okx={"classification":"volume_reconciled_rest_research_only",
             "instruments":{"BTC-USDT-SWAP":{"rolling_windows":{"15m":row}}}}
        self.assertIsNone(futures_report_sources({},okx,NOW)["windows"]["M15"]["preferred"])
        row["reconciled_m5"]=3
        self.assertEqual(futures_report_sources({},okx,NOW)["windows"]["M15"]["preferred"],"OKX")

    def test_svg_valid_and_no_imputed_samples(self):
        from src.report_feed import render_visible_liquidity_svg
        import xml.etree.ElementTree as ET
        sample={"timestamp_ms":int(NOW.timestamp())*1000,"bid":[{"price":59000,"btc":2}],"ask":[]}
        svg=render_visible_liquidity_svg({"samples":[sample]})
        root=ET.fromstring(svg)
        points=[e for e in root.iter() if e.tag.endswith("circle") and len(e)]
        self.assertEqual(len(points),1)
        self.assertIn("not a liquidation heatmap",svg)
