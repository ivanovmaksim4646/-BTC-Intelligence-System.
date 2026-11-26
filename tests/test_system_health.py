import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from src.system_health import evaluate, parse_time

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 26, 10, 0, tzinfo=UTC)


class SystemHealthTests(unittest.TestCase):
    def record(self, root, name, data):
        (root / name).write_text(json.dumps(data), encoding="utf-8")

    def fill(self, root, stamp, cloudflare=False):
        self.record(root, "BTC-intelligence-current.json", {
            "collected_at_utc": stamp, "status": "verified"})
        self.record(root, "BTC-analysis-current.json", {
            "analysed_at_utc": stamp, "fresh": True})
        self.record(root, "BTC-structure-current.json", {"collected_at_utc": stamp})
        self.record(root, "BTC-setup-candidates.json", {"evaluated_at_utc": stamp})
        self.record(root, "BTC-scheduler-health.json", {
            "recorded_at_utc": stamp,
            "event": "workflow_dispatch" if cloudflare else "schedule",
            "source": "cloudflare" if cloudflare else "github",
        })

    def test_missing_components_cannot_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate(Path(tmp), NOW)
            self.assertFalse(report["fully_operational_confirmed"])
            self.assertEqual(report["components"]["tradingview_intake"]["status"], "not_yet_verified")

    def test_github_schedule_does_not_prove_cloudflare(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fill(root, "2026-11-26T09:59:00Z")
            report = evaluate(root, NOW)
            self.assertEqual(report["components"]["kraken_collection"]["status"], "ok")
            self.assertEqual(report["components"]["cloudflare_dispatch"]["status"], "last_dispatch_unverified")
            self.assertFalse(report["fully_operational_confirmed"])

    def test_recent_cloudflare_event_and_saved_tv_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fill(root, "2026-11-26T09:59:00Z", cloudflare=True)
            (root / "BTC-tradingview-events.jsonl").write_text(
                json.dumps({"received_at_utc": "2026-11-26T09:59:00Z"}) + "\n", encoding="utf-8")
            report = evaluate(root, NOW)
            self.assertTrue(report["fully_operational_confirmed"])

    def test_stale_data_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fill(root, "2026-11-26T09:00:00Z", cloudflare=True)
            report = evaluate(root, NOW)
            self.assertEqual(report["components"]["kraken_collection"]["status"], "stale")
            self.assertEqual(report["components"]["cloudflare_dispatch"]["status"], "last_dispatch_stale")

    def test_bad_timestamp(self):
        self.assertIsNone(parse_time("invalid"))
        self.assertIsNone(parse_time("2026-11-26T09:00:00"))


if __name__ == "__main__":
    unittest.main()
