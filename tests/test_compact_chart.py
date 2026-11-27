import datetime as dt
import unittest
from src.report_feed import compact_chart

class CompactChartTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        now=dt.datetime.fromtimestamp(1800001200,dt.timezone.utc)
        bars=[dict(t=1800000000+i*300,o=100,h=102,l=99,c=101) for i in range(3)]
        doc=dict(source="OKX BTC-USDT-SWAP",status="verified",collected_at_utc=now.isoformat(),timeframes={"5m":dict(status="ok",bars=bars)})
        self.assertEqual(len(compact_chart(doc,None,now)["timeframes"]["5m"]["bars"]),3)
        bars[-1]["h"]=90
        self.assertEqual(compact_chart(doc,None,now)["timeframes"],{})
        self.assertEqual(compact_chart(doc,None,now+dt.timedelta(hours=1))["status"],"unverified_or_stale")
