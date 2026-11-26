import datetime as dt
import unittest
from src.official_bls_fed_calendar_v1 import parse_bls_html,parse_fed
NOW=dt.datetime(2026,11,26,tzinfo=dt.timezone.utc)
class CalendarTests(unittest.TestCase):
    def test_bls(self):
        r=parse_bls_html("<p>All times on calendar are Eastern Time</p><tr><td>Friday, December 04, 2026</td><td>08:30 AM</td><td>Employment Situation for November 2026</td></tr>",NOW,"https://www.bls.gov/schedule/2026/")
        self.assertEqual(r[0]["release_at_poland"],"2026-12-04T14:30:00+01:00")
        self.assertIsNone(r[0]["consensus"])
    def test_bls_no_timezone(self):
        with self.assertRaises(ValueError):parse_bls_html("no calendar",NOW,"test")
    def test_fed(self):
        r=parse_fed("<h4>2026 FOMC Meetings</h4><div>December</div><div>8-9*</div><h4>2027 FOMC Meetings</h4><div>January</div><div>26-27</div>",NOW)
        self.assertEqual(len(r),2)
        self.assertEqual(r[0]["release_at_poland"],"2026-12-09T20:00:00+01:00")
    def test_strategy_only(self):
        now=dt.datetime(2027,10,1,tzinfo=dt.timezone.utc)
        self.assertEqual(parse_fed("<h4>2027 FOMC Meetings</h4>October 26-27",now),[])
