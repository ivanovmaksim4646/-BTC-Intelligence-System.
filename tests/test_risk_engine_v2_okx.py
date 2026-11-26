import copy
import datetime as dt
import unittest
from src.risk_engine_v2_okx import calculate_paper, assess_snapshot, VENUE
from src.risk_engine_v1 import calculate as legacy_calculate,VENUE as LEGACY

NOW=dt.datetime(2026,11,26,13,0,tzinfo=dt.timezone.utc)
def stamp(minutes):
    return int((NOW+dt.timedelta(minutes=minutes)).timestamp())

def candidate(direction="long"):
    long=direction=="long"
    return {
        "source":VENUE,"model":"HTF_POI_QM_LTF","direction":direction,
        "poi_touch_verified":True,"qm_retest_verified":True,
        "futures_closed_candle_confirmed":True,
        "target_validated":True,"target_source":VENUE,
        "entry_price_source":"closed_retest_candle",
        "stop_source":"confirmed_qm_head","target_kind":"opposing_liquidity",
        "poi_touch_utc":stamp(-30),"qm_head_utc":stamp(-20),
        "retest_candle_close_utc":stamp(-5),"target_confirmed_utc":stamp(-60),
        "retest_close":100,"qm_head_extreme":90 if long else 110,
        "target_level":150 if long else 50,
    }
def snapshots():
    return ({"source":VENUE,"evaluated_at_utc":NOW.isoformat(),
             "classification":"futures_research_only","observations":[]},
            {"source":VENUE,"status":"verified",
             "timeframes":{tf:{"status":"ok"} for tf in
                ("5m","15m","1h","4h","1d","1w")}})

class RiskEngineOKXTests(unittest.TestCase):
    def test_long_paper_only_limit_1pct_and_5x(self):
        r=calculate_paper(candidate(),equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertEqual(r["venue"],VENUE)
        self.assertEqual(r["evidence"]["venue"],VENUE)
        self.assertLessEqual(r["risk_usdt_estimate"],100.01)
        self.assertLessEqual(r["notional_usdt"],50000.01)
        self.assertGreaterEqual(r["rr_net_estimate"],3)
        self.assertFalse(r["execution_ready"])
        self.assertIsNone(r["trade_signal"])
    def test_short_paper_only(self):
        r=calculate_paper(candidate("short"),equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertLess(r["take_profit"],r["entry"])
        self.assertGreater(r["stop_loss"],r["entry"])
    def test_venue_mix_rejected(self):
        for key in ("source","target_source"):
            with self.subTest(key=key):
                c=candidate()
                c[key]=LEGACY
                r=calculate_paper(c,equity_usdt=10000,now=NOW)
                self.assertEqual(r["status"],"withheld")
                self.assertIsNone(r["trade_signal"])
    def test_risk_above_one_percent_rejected(self):
        for fraction in (0.011,0.02,0.04,True,0.0):
            with self.subTest(fraction=fraction):
                r=calculate_paper(candidate(),equity_usdt=10000,risk_fraction=fraction,now=NOW)
                self.assertEqual(r["status"],"withheld")
    def test_leverage_above_five_rejected(self):
        for lev in (5.01,6,20,True,0):
            with self.subTest(leverage=lev):
                self.assertEqual(calculate_paper(candidate(),equity_usdt=10000,
                    leverage_cap=lev,now=NOW)["status"],"withheld")
    def test_lower_risk_and_leverage_accepted(self):
        r=calculate_paper(candidate(),equity_usdt=10000,
            risk_fraction=0.005,leverage_cap=2,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertLessEqual(r["risk_usdt_estimate"],50.01)
        self.assertLessEqual(r["notional_usdt"],20000.01)
    def test_no_fabricated_target(self):
        c=candidate();c["target_validated"]=False
        r=calculate_paper(c,equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"withheld")
        self.assertIsNone(r["take_profit"])
    def test_rr_below_three_rejected(self):
        c=candidate();c["target_level"]=125
        r=calculate_paper(c,equity_usdt=10000,now=NOW)
        self.assertEqual(r["reason"],"rr_below_three_after_costs")
    def test_no_auto_trade_even_for_historical_observation(self):
        research,candles=snapshots()
        research["observations"]=[{"direction":"long","status":"historical_sequence_observed",
                                   "qm_shoulder":100}]
        r=assess_snapshot(research,candles,NOW)
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertEqual(r["scenarios"],[])
        self.assertEqual(r["candidates_inspected"],1)
        self.assertTrue(r["okx_closed_candles_verified"])
        self.assertIsNone(r["trade_signal"])
    def test_missing_candles_fail_closed(self):
        research,_=snapshots()
        r=assess_snapshot(research,None,NOW)
        self.assertFalse(r["okx_closed_candles_verified"])
        self.assertIn("missing_or_unverified_okx_futures_candles",r["reasons"])
    def test_legacy_defaults_unchanged(self):
        c=candidate();c["source"]=LEGACY;c["target_source"]=LEGACY
        r=legacy_calculate(c,equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertEqual(r["evidence"]["venue"],LEGACY)
    def test_stale_retest_rejected(self):
        c=candidate();c["retest_candle_close_utc"]=stamp(-31)
        self.assertEqual(calculate_paper(c,equity_usdt=10000,now=NOW)["status"],"withheld")

if __name__=="__main__":unittest.main()
