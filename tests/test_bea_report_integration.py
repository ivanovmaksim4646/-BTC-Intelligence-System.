import datetime as dt
import unittest
from src.report_feed import build
from src.official_bea_calendar_v1 import parse_bea
class IntegrationTests(unittest.TestCase):
    def test_calendar_and_stale(self):
        now=dt.datetime(2026,11,26,tzinfo=dt.timezone.utc)
        data=parse_bea({"Gross Domestic Product":{"release_dates":["2026-12-23T13:30:00Z"]},"Personal Income and Outlays":{"release_dates":["2026-12-23T13:30:00Z"]}},now)
        result=build({}, {}, {}, {}, {}, now=now, bea=data)
        self.assertEqual(len(result["economic_calendar"]["events"]),2)
        self.assertIsNone(result["trade_signal"])
        stale=build({}, {}, {}, {}, {}, now=now+dt.timedelta(days=2), bea=data)
        self.assertEqual(stale["economic_calendar"]["status"],"missing_or_stale")
