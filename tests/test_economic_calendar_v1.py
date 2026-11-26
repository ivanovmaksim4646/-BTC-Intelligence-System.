import unittest,datetime as dt
from src.economic_calendar_v1 import parse
class CalendarTests(unittest.TestCase):
    def test_dst(self):
        raw="BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Consumer Price Index\nDTSTART;TZID=America/New_York:20260312T083000\nEND:VEVENT\nEND:VCALENDAR"
        r=parse(raw,dt.datetime(2026,3,1,tzinfo=dt.timezone.utc))
        self.assertEqual(r[0]["scheduled_warsaw"],"2026-03-12T13:30:00+01:00")
        self.assertIsNone(r[0]["forecast"])
    def test_unknown_time(self):
        raw="BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Producer Price Index\nDTSTART:20260312\nEND:VEVENT\nEND:VCALENDAR"
        self.assertEqual(parse(raw,dt.datetime(2026,3,1,tzinfo=dt.timezone.utc)),[])
