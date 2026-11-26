import copy
import datetime as dt
import math
import unittest
from src.risk_engine_v1 import calculate, assess_snapshot, VENUE

NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)
T=lambda minutes: int((NOW+dt.timedelta(minutes=minutes)).timestamp())
def candidate(direction="long"):
    long=direction=="long"
    return {
        "source":VENUE,"model":"HTF_POI_QM_LTF","direction":direction,
        "poi_touch_verified":True,"qm_retest_verified":True,
        "futures_closed_candle_confirmed":True,"target_validated":True,
        "target_source":VENUE,"entry_price_source":"closed_retest_candle",
        "stop_source":"confirmed_qm_head","target_kind":"opposing_liquidity",
        "poi_touch_utc":T(-30),"qm_head_utc":T(-20),
        "retest_candle_close_utc":T(-5),"target_confirmed_utc":T(-60),
        "retest_close":100,"qm_head_extreme":90 if long else 110,
        "target_level":150 if long else 50,
    }

class RiskEngineTests(unittest.TestCase):
    def test_long_paper_scenario_with_strict_order(self):
        r=calculate(candidate(),equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertFalse(r["entry_signal"])
        self.assertIsNone(r["trade_signal"])
        self.assertGreaterEqual(r["rr_net_estimate"],3)
        self.assertLessEqual(r["risk_usdt_estimate"],100.01)
        self.assertLessEqual(r["notional_usdt"],50000)
        self.assertLess(r["stop_loss"],r["entry"])
        self.assertGreater(r["take_profit"],r["entry"])

    def test_short_paper_scenario(self):
        r=calculate(candidate("short"),equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertGreater(r["stop_loss"],r["entry"])
        self.assertLess(r["take_profit"],r["entry"])

    def test_rr3_not_fabricated(self):
        x=candidate()
        x["target_level"]=125
        r=calculate(x,equity_usdt=10000,now=NOW)
        self.assertEqual(r["status"],"withheld")
        self.assertEqual(r["reason"],"rr_below_three_after_costs")
        self.assertIsNone(r["take_profit"])

    def test_missing_target_blocks(self):
        x=candidate()
        x["target_validated"]=False
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["status"],"withheld")

    def test_cross_venue_target_blocks(self):
        x=candidate()
        x["target_source"]="Kraken Spot"
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["status"],"withheld")

    def test_target_confirmed_in_future_blocks(self):
        x=candidate()
        x["target_confirmed_utc"]=T(-2)
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["reason"],
                         "stale_future_or_out_of_order_evidence")

    def test_future_retest_blocks(self):
        x=candidate()
        x["retest_candle_close_utc"]=T(1)
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["status"],"withheld")

    def test_stale_retest_blocks(self):
        x=candidate()
        x["retest_candle_close_utc"]=T(-40)
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["status"],"withheld")

    def test_bad_order_blocks(self):
        x=candidate()
        x["qm_head_extreme"]=105
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["reason"],
                         "invalid_entry_stop_target_order")

    def test_nan_blocks(self):
        x=candidate()
        x["target_level"]=float("nan")
        self.assertEqual(calculate(x,equity_usdt=10000,now=NOW)["status"],"withheld")

    def test_cap_limits_exposure(self):
        r=calculate(candidate(),equity_usdt=10000,leverage_cap=1,now=NOW)
        self.assertEqual(r["status"],"paper_scenario_only")
        self.assertLessEqual(r["notional_usdt"],10000)

    def test_invalid_risk_fraction_blocks(self):
        r=calculate(candidate(),equity_usdt=10000,risk_fraction=0.04,now=NOW)
        self.assertEqual(r["reason"],"invalid_risk_limits")

    def test_no_trade_live_snapshot(self):
        o={"source":VENUE,"evaluated_at_utc":NOW.isoformat(),"observations":[{
            "status":"historical_sequence_observed","qm_shoulder":100,
            "qm_head":90,"direction":"long"}]}
        r=assess_snapshot(o,NOW)
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertIsNone(r["trade_signal"])
        self.assertEqual(r["scenarios"],[])

    def test_no_trade_stale_snapshot(self):
        o={"source":VENUE,"evaluated_at_utc":"2026-11-25T00:00:00Z","observations":[]}
        self.assertIn("stale_research_observations",assess_snapshot(o,NOW)["reasons"])

if __name__=="__main__":
    unittest.main()
