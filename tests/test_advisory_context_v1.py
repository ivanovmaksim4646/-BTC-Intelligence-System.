import datetime as dt
import unittest
from src.advisory_context_v1 import breadth,volatility,stablecoins,etf_flows,reconciled_coverage
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
    def test_etf(self):
        html="<table><tr><th>Date</th><th>IBIT</th><th>FBTC</th><th>BTC</th><th>Total</th></tr><tr><td>27 Nov 2026</td><td>12.0</td><td>(2.0)</td><td>1.0</td><td>11.0</td></tr><tr><td>26 Nov 2026</td><td>12.0</td><td>-</td><td>1.0</td><td>13.0</td></tr></table>"
        result=etf_flows(html,self.now)
        self.assertEqual(result["latest"]["net_flow_usd_m"],11)
        self.assertEqual(len(result["recent_sessions"]),1)
    def test_flow_coverage(self):
        end=int(self.now.timestamp())*1000
        row=dict(end_ms=end,start_ms=end-14400000,required_m5=48,reconciled_m5=48,delta_btc_reconciled="10",volume_btc_reconciled="100")
        doc=dict(end_ms=end,instruments={"BTC-USDT":{"rolling_windows":{"4h":row}}})
        self.assertIn("4h",reconciled_coverage(doc,self.now)["instruments"]["BTC-USDT"])
        row["reconciled_m5"]=47
        self.assertNotIn("4h",reconciled_coverage(doc,self.now)["instruments"]["BTC-USDT"])
    def test_deribit_envelope(self):
        self.assertEqual(volatility({"result":{"data":[[self.now.timestamp()*1000,1,1,1,45]]}},self.now)["status"],"observed")
