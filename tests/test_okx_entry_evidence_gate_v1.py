import datetime as dt
import unittest
from unittest.mock import patch
from src.okx_entry_evidence_gate_v1 import evaluate,confirmed_pivots,VENUE
from src.okx_outcome_tracker_v1 import check_entry

NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
EPOCH=int(NOW.timestamp())
ENTRY_OPEN=EPOCH-300
def series(step,n=40,base=100):
    start=ENTRY_OPEN-(n-1)*step
    return [{"t":start+i*step,"o":base,"h":base+1,"l":base-1,"c":base}
            for i in range(n)]
def fixture():
    m5=series(300)
    # Latest entry must be a true shoulder retest at 100
    m5[-1].update({"o":100,"h":101,"l":99.8,"c":100.1})
    h1=series(3600,40)
    h4=series(14400,40)
    # Confirmed opposing pivot 3 bars before last (pivot +2 confirm).
    for bars in (h1,h4):
        bars[-4]["h"]=115
    return {"source":VENUE,"status":"verified",
       "collected_at_utc":NOW.isoformat(),
       "timeframes":{"5m":{"status":"ok","bars":m5},
                     "1h":{"status":"ok","bars":h1},
                     "4h":{"status":"ok","bars":h4}}}
def observations():
    return [{"source":VENUE,"status":"observed_not_trade",
       "symbol":"OKX:BTCUSDT.P","event_id":"test-okx-observation-1",
       "event_close_ms":EPOCH*1000,"side":"long",
       "corroboration":"closed_candle_price_consistent_only"}]
def qm():
    return [{"direction":"long","head_time":ENTRY_OPEN-3000,
      "structural_extreme_time":ENTRY_OPEN-1800,
      "left_shoulder":100,"head_extreme":95}]

class EntryEvidenceGateTests(unittest.TestCase):
    def test_denies_missing_tv_evidence(self):
        r=evaluate(fixture(),[],NOW)
        self.assertEqual(r["paper_entries"],[])
        self.assertIn("no_same_bar_independently_corroborated_okx_tv_alert",r["reasons"])
    def test_denies_bingx_tv_evidence(self):
        bad=observations();bad[0]["symbol"]="BINGX:BTCUSDT.P"
        self.assertEqual(evaluate(fixture(),bad,NOW)["paper_entries"],[])
    def test_denies_stale_candle_snapshot(self):
        snap=fixture();snap["collected_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        self.assertIn("missing_or_stale_verified_okx_candles",evaluate(snap,observations(),NOW)["reasons"])
    def test_denies_wrong_venue(self):
        snap=fixture();snap["source"]="BingX USD-M Perpetual BTC-USDT"
        self.assertEqual(evaluate(snap,observations(),NOW)["paper_entries"],[])
    def test_no_qm_denies_all_paper_entries(self):
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=[]):
            r=evaluate(fixture(),observations(),NOW)
        self.assertEqual(r["paper_entries"],[])
        self.assertEqual(r["decision"],"NO_TRADE")
    def test_no_prior_poi_touch_denies(self):
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=qm()),\
             patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[]):
            r=evaluate(fixture(),observations(),NOW)
        self.assertEqual(r["paper_entries"],[])
    def test_preexisting_target_pivot_requires_confirmation(self):
        bars=series(3600,40)
        bars[-1]["h"]=150
        self.assertNotIn(150,[x["level"] for x in confirmed_pivots(bars,3600,"long",EPOCH)])
    def test_qm_target_and_poi_validated_in_isolation_paper_only(self):
        snap=fixture()
        m5=snap["timeframes"]["5m"]["bars"]
        poi={"direction":"long","low":99,"high":101,"formed":ENTRY_OPEN-10000}
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=qm()),\
             patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[poi]):
            r=evaluate(snap,observations(),NOW)
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertIsNone(r["trade_signal"])
        self.assertGreaterEqual(r["paper_entries_count"] if "paper_entries_count" in r else len(r["paper_entries"]),1)
        p=r["paper_entries"][0]
        self.assertTrue(check_entry(p))
        self.assertEqual(p["source"],VENUE)
        self.assertEqual(p["entry_close_utc"],EPOCH)
        self.assertEqual(p["take_profit"],115)
        self.assertLessEqual(p["risk_fraction"],0.01)
        self.assertFalse(p["entry_signal"])
        self.assertEqual(p["execution"],"not_executed")
    def test_lookahead_target_not_allowed(self):
        snap=fixture()
        for tf in ("1h","4h"):
            bars=snap["timeframes"][tf]["bars"]
            bars[-4]["h"]=101
            bars[-1]["h"]=150
        poi={"direction":"long","low":99,"high":101,"formed":ENTRY_OPEN-10000}
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=qm()),\
             patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[poi]):
            result=evaluate(snap,observations(),NOW)
        self.assertEqual(result["paper_entries"],[])
    def test_missing_latest_candle_no_backdated_entry(self):
        s=fixture()
        for tf in ("5m",):
            s["timeframes"][tf]["bars"].pop()
        self.assertEqual(evaluate(s,observations(),NOW)["paper_entries"],[])
    def test_fvg_is_not_arbitrary_rr_target(self):
        p=confirmed_pivots(fixture()["timeframes"]["1h"]["bars"],3600,"long",EPOCH)
        self.assertEqual(p[-1]["level"],115)

if __name__=="__main__":unittest.main()
