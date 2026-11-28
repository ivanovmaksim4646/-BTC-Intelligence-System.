import datetime as dt
import unittest
from src.advisory_context_v1 import breadth,volatility,stablecoins
class AdvisoryTests(unittest.TestCase):
    def setUp(self):self.now=dt.datetime(2026,11,28,15,tzinfo=dt.timezone.utc)
    def test_breadth(self):
        b=dict(asof_utc=self.now.isoformat(),btc_d_pct=60,total_usd=100,total_ex_btc_usd=40,total_ex_btc_eth_usd=25)
        self.assertEqual(breadth({"breadth":b},self.now)["status"],"observed")
        b["asof_utc"]=(self.now-dt.timedelta(hours=1)).isoformat()
        self.assertEqual(breadth({"breadth":b},self.now)["status"],"missing_or_stale")
    def test_vol(self):
        self.assertEqual(volatility({"result":[[self.now.timestamp()*1000,1,1,1,45]]},self.now)["annualized_implied_volatility_pct"],45)
    def test_stables(self):
        r=dict(id="tether",last_updated=self.now.isoformat(),market_cap=100,circulating_supply=100)
        self.assertIn("tether",stablecoins([r],self.now))
        r["market_cap"]=-1
        self.assertEqual(stablecoins([r],self.now),{})
