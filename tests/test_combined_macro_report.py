import datetime as dt
import unittest
from src.report_feed import build
from src.official_bea_calendar_v1 import parse_bea
from src.official_bls_fed_calendar_v1 import parse_fed,parse_bls_html
NOW=dt.datetime(2026,11,26,tzinfo=dt.timezone.utc)
class Combined(unittest.TestCase):
    def test_merge_and_stale(self):
        bea=parse_bea({"Gross Domestic Product":{"release_dates":["2026-12-23T13:30:00Z"]},"Personal Income and Outlays":{"release_dates":["2026-12-23T13:30:00Z"]}},NOW)
        fed=parse_fed("<h4>2026 FOMC Meetings</h4>December 8-9",NOW)
        bls=parse_bls_html("All times on calendar are Eastern Time Friday, December 04, 2026 08:30 AM Employment Situation for November 2026",NOW,"https://www.bls.gov/schedule/2026/")
        extra={"generated_at_utc":NOW.isoformat(),"sources":{"BLS":{"status":"official_schedule_only"},"FED":{"status":"official_schedule_only"}},"events":fed+bls}
        d=build({}, {}, {}, {}, {}, now=NOW, bea=bea, bls_fed=extra)
        self.assertEqual(len(d["economic_calendar"]["events"]),4)
        self.assertIsNone(d["trade_signal"])
        extra["generated_at_utc"]="2026-11-20T00:00:00Z"
        d=build({}, {}, {}, {}, {}, now=NOW, bea=bea, bls_fed=extra)
        self.assertEqual(len(d["economic_calendar"]["events"]),2)
        self.assertEqual(d["economic_calendar"]["sources"]["FED"]["status"],"missing_or_stale")
