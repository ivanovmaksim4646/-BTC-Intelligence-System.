import datetime as dt
import unittest
from src.macro_calendar_v1 import build, normalize_event

NOW = dt.datetime(2026, 11, 26, 19, tzinfo=dt.timezone.utc)
def sample(**kwargs):
    r = {"agency": "BLS", "category": "CPI", "title": "Consumer Price Index",
         "release_et": "2026-12-10T08:30:00",
         "source_url": "https://www.bls.gov/schedule/news_release/cpi.htm"}
    r.update(kwargs)
    return r

class MacroCalendarTests(unittest.TestCase):
    def test_poland_timezone_winter(self):
        e = normalize_event(sample(), NOW)
        self.assertEqual(e["release_at_poland"], "2026-12-10T14:30:00+01:00")
        self.assertIsNone(e["consensus"])
        self.assertIsNone(e["btc_reaction"])
    def test_poland_timezone_summer(self):
        e = normalize_event(sample(release_et="2027-03-16T08:30:00"), NOW)
        self.assertEqual(e["release_at_poland"], "2027-03-16T13:30:00+01:00")
    def test_reject_untrusted_url(self):
        with self.assertRaises(ValueError):
            normalize_event(sample(source_url="https://evil.example/"), NOW)
    def test_reject_mismatched_agency(self):
        with self.assertRaises(ValueError):
            normalize_event(sample(agency="BEA"), NOW)
    def test_reject_nonexistent_dst_time(self):
        with self.assertRaises(ValueError):
            normalize_event(sample(release_et="2027-03-14T02:30:00"), NOW)
    def test_reject_ambiguous_dst_time(self):
        with self.assertRaises(ValueError):
            normalize_event(sample(release_et="2027-11-07T01:30:00"), NOW)
    def test_dedup_and_no_trade(self):
        r = build([sample(), sample()], NOW)
        self.assertEqual(len(r["events"]), 1)
        self.assertEqual(r["decision"], "NO_TRADE")
    def test_empty_does_not_infer_no_events(self):
        r = build([], NOW)
        self.assertEqual(r["status"], "no_verified_events")
    def test_conflicting_duplicates_fail(self):
        with self.assertRaises(ValueError):
            build([sample(), sample(title="Changed")], NOW)

if __name__ == "__main__":
    unittest.main()
