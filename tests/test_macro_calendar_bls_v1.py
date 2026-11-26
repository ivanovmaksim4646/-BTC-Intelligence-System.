import datetime as dt
import unittest
from src.macro_calendar_bls_v1 import parse_bls_ics
NOW = dt.datetime(2026, 11, 26, 19, tzinfo=dt.timezone.utc)

def calendar(dtstart="DTSTART;TZID=America/New_York:20261210T083000", name="Consumer Price Index"):
    return ("BEGIN:VCALENDAR\nBEGIN:VEVENT\n"+dtstart+"\nSUMMARY:"+name+
            "\nEND:VEVENT\nEND:VCALENDAR")

class BlsCalendarTests(unittest.TestCase):
    def test_valid_cpi_and_poland_conversion(self):
        e = parse_bls_ics(calendar(), NOW)["events"][0]
        self.assertEqual(e["release_at_poland"], "2026-12-10T14:30:00+01:00")
        self.assertIsNone(e["actual"])
    def test_reject_utc_without_explicit_conversion(self):
        with self.assertRaises(ValueError):
            parse_bls_ics(calendar("DTSTART:20261210T133000Z"), NOW)
    def test_invalid_envelope(self):
        with self.assertRaises(ValueError):
            parse_bls_ics("not an ics", NOW)
    def test_no_supported_events_fails_closed(self):
        with self.assertRaises(ValueError):
            parse_bls_ics(calendar(name="Another Report"), NOW)
    def test_reject_ambiguous_dst(self):
        with self.assertRaises(ValueError):
            parse_bls_ics(calendar(dtstart="DTSTART;TZID=America/New_York:20271107T013000"), NOW)
if __name__ == "__main__":
    unittest.main()
