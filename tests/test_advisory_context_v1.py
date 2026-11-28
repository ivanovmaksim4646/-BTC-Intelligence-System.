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
        html="<table><tr><th>Date</th><th>IBIT</th><th>FBTC</th><th>BTC</th><th></th></tr><tr><td>27 Nov 2026</td><td>12.0</td><td>(2.0)</td><td>1.0</td><td>11.0</td></tr><tr><td>26 Nov 2026</td><td>12.0</td><td>-</td><td>1.0</td><td>13.0</td></tr></table>"
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

    def test_gap_aware_history(self):
        from src.advisory_history_v1 import flow_segments
        end=1800000000
        def row(t,d):
            return dict(instrument="BTC-USDT",volume_reconciled=True,end_ms=t,start_ms=t-300000,
                       delta_btc_reconciled=d,volume_btc_reconciled=10,open_usdt=100,close_usdt=99)
        a=flow_segments([row(end-600000,1),row(end,2)],end)["BTC-USDT"]
        self.assertEqual(a["consecutive_m5"],1)
        self.assertEqual(a["series"][0]["cumulative_reconciled_delta_btc"],2)
        self.assertEqual(a["windows"]["5m"]["divergence_candidate"],"price_down_delta_positive")
        b=flow_segments([row(end,2),row(end,3)],end)["BTC-USDT"]
        self.assertEqual(b["consecutive_m5"],0)

    def test_liquidation_page(self):
        from src.advisory_events_v1 import liquidation_map
        row=dict(timestamp_ms=int(self.now.timestamp()*1000),price="59050",position_direction="LONG",reported_amount="1")
        d=dict(source="Bitget USDT-FUTURES BTCUSDT",classification="exchange_reported_liquidation_orders_not_execution_certified",status="observed_page",records=[row,row])
        a=liquidation_map(d,self.now)
        self.assertEqual(a["records"],1)
        self.assertEqual(a["bins"][0]["LONG"],1)
        self.assertIsNone(a["liquidation_heatmap"])
    def test_surprise_timestamp(self):
        from src.advisory_events_v1 import surprise
        release=self.now.isoformat()
        f=dict(series="CPI",period="2026-10",unit="pct",release_at_utc=release,value=.2,observed_at_utc=(self.now-dt.timedelta(minutes=5)).isoformat())
        a=dict(f,value=.3,observed_at_utc=release,first_release_verified=True)
        self.assertAlmostEqual(surprise(f,a),.1)
        self.assertIsNone(surprise(dict(f,observed_at_utc=release),a))
    def test_reaction_gap(self):
        from src.advisory_events_v1 import btc_reaction
        t=int(self.now.timestamp())
        rows=[dict(t=x,o=100,h=103,l=99,c=102 if x==t else 100) for x in (t-300,t,t+600)]
        d=dict(source="OKX BTC-USDT-SWAP",status="verified",timeframes={"5m":{"status":"ok","bars":rows}})
        a=btc_reaction({"release_at_utc":self.now.isoformat()},d,self.now+dt.timedelta(minutes=15))
        self.assertAlmostEqual(a["windows"]["5m"]["return_pct"],2)
        self.assertNotIn("15m",a["windows"])
    def test_forecast_match(self):
        from src.advisory_events_v1 import forecast_matches
        t=(self.now+dt.timedelta(days=1)).isoformat()
        events=[dict(category="CPI",release_at_utc=t,source_url="https://www.bls.gov/")]
        rows=[dict(title="CPI m/m",country="USD",date=t,forecast="0.2%",previous="0.3%")]
        self.assertEqual(len(forecast_matches(rows,events,self.now)),1)
        rows[0]["date"]=self.now.isoformat()
        self.assertEqual(forecast_matches(rows,events,self.now),[])

    def test_smart_sim_sides(self):
        from src.advisory_liquidations_v1 import smart_sim
        raw=dict(ok=True,estimated=True,symbol="BTC",ts=int(self.now.timestamp()),study_age_s=20,current_price=100,target_price=95,move_pct=-5,clusters=[dict(price=98,side="long",notional_usd=500),dict(price=80,side="long",notional_usd=99),dict(price=105,side="short",notional_usd=100)])
        self.assertEqual(smart_sim(raw,-5,self.now)["clusters"][0]["side"],"LONG")
        self.assertEqual(smart_sim(raw,-5,self.now)["total_estimated_crossed_usd"],500)
        raw["clusters"][0]["side"]="bad"
        with self.assertRaises(ValueError):smart_sim(raw,-5,self.now)
    def test_smart_empty(self):
        from src.advisory_liquidations_v1 import smart_sim,smart_realized
        self.assertEqual(smart_sim(dict(ok=True,estimated=True,symbol="BTC",empty=True),5)["status"],"unavailable")
        self.assertEqual(smart_realized(dict(symbol="BTC",window_minutes=240,clusters=[],generated_at=int(self.now.timestamp())),self.now)["status"],"empty_unverified")

    def test_swole_freshness(self):
        from src.advisory_liquidations_v1 import swole
        d=dict(coin="BTC",price=59000,as_of=int(self.now.timestamp()*1000),estimated=True,has_data=True,model_version="v1",levels={"long":[],"short":[]},totals=[dict(pct=.05,long_usd=1,short_usd=2)])
        self.assertEqual(swole(d,"levels",self.now)["status"],"provider_estimate")
        self.assertEqual(swole(d,"levels",self.now+dt.timedelta(hours=1))["status"],"stale_or_unverified")
