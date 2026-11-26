import datetime as dt
import unittest
from src.report_delivery_audit_v1 import evaluate
NOW=dt.datetime(2026,11,26,19,55,tzinfo=dt.timezone.utc)
def feed(**kwargs):
    x={"collected_at_utc":"2026-11-26T19:50:00Z",
       "generated_at_utc":"2026-11-26T19:51:00Z",
       "report_data_status":"verified",
       "okx_confluence":{"status":"verified"},
       "trade_signal":None}
    x.update(kwargs)
    return x
def scheduler(**kwargs):
    x={"recorded_at_utc":"2026-11-26T19:50:30Z"}
    x.update(kwargs)
    return x
class DeliveryAuditTests(unittest.TestCase):
    def test_fresh_feed_not_proof_of_push(self):
        a=evaluate(feed(),scheduler(),NOW)
        self.assertTrue(a["feed_fresh"])
        self.assertFalse(a["push_notification_confirmed"])
        self.assertFalse(a["delivery_confirmed"])
    def test_stale_feed(self):
        self.assertIn("feed_missing_stale_or_future",evaluate(feed(collected_at_utc="2026-11-26T19:00:00Z"),scheduler(),NOW)["issues"])
    def test_future_feed(self):
        self.assertFalse(evaluate(feed(generated_at_utc="2026-11-26T20:01:00Z"),scheduler(),NOW)["feed_fresh"])
    def test_unqualified_data(self):
        self.assertIn("report_data_not_unqualified",evaluate(feed(report_data_status="withhold_or_qualify"),scheduler(),NOW)["issues"])
    def test_confluence_partial(self):
        self.assertIn("confluence_unverified_or_partial",evaluate(feed(okx_confluence={"status":"research_partial"}),scheduler(),NOW)["issues"])
    def test_stale_scheduler(self):
        self.assertFalse(evaluate(feed(),scheduler(recorded_at_utc="2026-11-26T19:00:00Z"),NOW)["trigger_fresh"])
    def test_before_collect_generation(self):
        a=evaluate(feed(generated_at_utc="2026-11-26T19:49:00Z"),scheduler(),NOW)
        self.assertIn("feed_generated_before_collection",a["issues"])
    def test_poland_slots(self):
        a=evaluate(feed(),scheduler(),NOW)
        self.assertEqual(a["slots"]["morning"]["local_time"],"08:15")
        self.assertEqual(a["slots"]["pre_new_york"]["local_time"],"13:45")
        self.assertEqual(a["slots"]["morning"]["time_zone"],"Europe/Warsaw")
    def test_no_time_zone_rejected(self):
        with self.assertRaises(ValueError):evaluate({}, {}, dt.datetime(2026,11,26))
    def test_fail_closed_invalid_payload(self):
        a=evaluate(None,None,NOW)
        self.assertFalse(a["can_claim_unqualified_report"])
        self.assertFalse(a["delivery_confirmed"])
if __name__=="__main__":unittest.main()
