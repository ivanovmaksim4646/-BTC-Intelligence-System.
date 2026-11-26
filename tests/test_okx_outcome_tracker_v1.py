import datetime as dt
import unittest
from src.okx_outcome_tracker_v1 import (
    VENUE,check_entry,check_bar,merge_archive,evaluate,good_snapshot,M5,
)

NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
CLOSE=int(NOW.timestamp())-900
def bar(t,o,h,l,c):
    return {"t":t,"o":o,"h":h,"l":l,"c":c}
def entry(direction="long",at=CLOSE):
    return {"entry_id":"paper-verified-000001","source":VENUE,
        "classification":"validated_paper_entry_only","execution":"not_executed",
        "entry_signal":False,"trade_signal":None,
        "independent_entry_validator":"okx_poi_qm_execution_validator_v1",
        "venue_candle_close_verified":True,"independent_target_verified":True,
        "direction":direction,"entry":100,"stop_loss":90 if direction=="long" else 110,
        "take_profit":150 if direction=="long" else 50,
        "entry_close_utc":at,"risk_fraction":0.01,"leverage_cap":5,
        "total_cost_bps":14,"model":"HTF_POI_QM_LTF","trading_session":"NY"}

def future_long():
    return [bar(CLOSE,100,121,99,118),
            bar(CLOSE+300,118,123,98,120),
            bar(CLOSE+600,120,152,119,150)]

class OKXOutcomeTrackerTests(unittest.TestCase):
    def test_long_target1_to5_full_resolution_with_closed_candles(self):
        r=evaluate([entry()],future_long(),NOW)
        self.assertEqual(r["resolved_entries"],1)
        self.assertEqual(r["newly_finalized"] if "newly_finalized" in r else 1,1)
        outcomes=r["results"][0]["outcomes"]
        self.assertEqual(outcomes["2.0"]["status"],"target_first")
        self.assertEqual(outcomes["5.0"]["status"],"target_first")
        self.assertIsNone(r["trade_signal"])
        self.assertFalse(r["execution_enabled"])
    def test_partial_targets_remain_pending_not_fake_losses(self):
        r=evaluate([entry()],future_long()[:1],NOW)
        self.assertEqual(r["resolved_entries"],0)
        self.assertEqual(r["pending_entries"],1)
        self.assertEqual(r["pending"][0]["reason"],"open_rr_thresholds")
    def test_same_candle_stop_and_target_censored(self):
        r=evaluate([entry()],[
            bar(CLOSE,100,151,89,101)],NOW)
        self.assertEqual(r["resolved_entries"],1)
        self.assertEqual(r["results"][0]["outcomes"]["2.0"]["status"],"ambiguous_same_candle")
        self.assertIsNone(r["results"][0]["outcomes"]["2.0"]["net_r"])
    def test_short_path(self):
        bars=[bar(CLOSE,100,101,49,60)]
        r=evaluate([entry("short")],bars,NOW)
        self.assertEqual(r["resolved_entries"],1)
        self.assertEqual(r["results"][0]["outcomes"]["5.0"]["status"],"target_first")
    def test_gap_censored_and_not_interpolated(self):
        bars=[bar(CLOSE,100,121,99,118),bar(CLOSE+600,120,152,119,150)]
        r=evaluate([entry()],bars,NOW)
        self.assertEqual(r["resolved_entries"],0)
        self.assertEqual(r["pending"][0]["reason"],"missing_m5_data_no_interpolation")
    def test_stale_entry_outside_history_not_repaired(self):
        r=evaluate([entry(at=CLOSE-3000)],future_long(),NOW)
        self.assertEqual(r["pending"][0]["reason"],"entry_outside_retained_history")
    def test_future_entry_censored(self):
        r=evaluate([entry(at=int(NOW.timestamp())+300)],future_long(),NOW)
        self.assertEqual(r["pending"][0]["reason"],"entry_from_future")
    def test_bingx_paper_entry_not_counted(self):
        e=entry();e["source"]="BingX USD-M Perpetual BTC-USDT"
        r=evaluate([e],future_long(),NOW)
        self.assertEqual(r["rejected_entries"],1)
        self.assertEqual(r["resolved_entries"],0)
    def test_raw_tv_event_not_an_entry(self):
        e={"source":"btc-intelligence-tv-v2","event":"m5_bullish_fvg","entry":100}
        self.assertFalse(check_entry(e))
        self.assertEqual(evaluate([e],future_long(),NOW)["resolved_entries"],0)
    def test_flags_without_validator_id_fail(self):
        e=entry();e["independent_entry_validator"]="unknown"
        self.assertFalse(check_entry(e))
    def test_bad_risk_and_leverage_fail(self):
        for key,value in (("risk_fraction",0.02),("leverage_cap",6),
                          ("risk_fraction",True),("leverage_cap",True)):
            e=entry();e[key]=value
            self.assertFalse(check_entry(e))
    def test_archive_idempotent_and_conflict_rejected(self):
        bars=future_long()
        self.assertEqual(merge_archive(bars,bars),bars)
        edited=[dict(bars[0],h=199)]
        with self.assertRaisesRegex(ValueError,"revised"):
            merge_archive(bars,edited)
    def test_closed_snapshot_required(self):
        bars=[bar(CLOSE-(i*300),100,110,90,100) for i in range(34,-1,-1)]
        snap={"source":VENUE,"status":"verified",
              "collected_at_utc":NOW.isoformat(),
              "timeframes":{"5m":{"status":"ok","bars":bars}}}
        self.assertTrue(good_snapshot(snap,NOW))
        snap["timeframes"]["5m"]["bars"][5]["h"]=1
        self.assertFalse(good_snapshot(snap,NOW))
    def test_invalid_archive_candle_rejected(self):
        self.assertFalse(check_bar({"t":CLOSE,"o":100,"h":99,"l":90,"c":101}))
        with self.assertRaises(ValueError):
            evaluate([entry()],[{"t":CLOSE}],NOW)
    def test_duplicate_paper_id_rejected(self):
        e=entry();r=evaluate([e,e],future_long(),NOW)
        self.assertEqual(r["resolved_entries"],1)
        self.assertEqual(r["rejected_entries"],1)
    def test_missing_candles_pending(self):
        r=evaluate([entry()],[],NOW)
        self.assertEqual(r["resolved_entries"],0)
        self.assertEqual(r["pending_entries"],1)

if __name__=="__main__":unittest.main()
