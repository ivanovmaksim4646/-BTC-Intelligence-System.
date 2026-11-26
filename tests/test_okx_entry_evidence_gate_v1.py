import datetime as dt
import unittest
from unittest.mock import patch
from src.okx_entry_evidence_gate_v1 import evaluate,confirmed_pivots,chronological_break,prior_poi_zones,VENUE
from src.okx_outcome_tracker_v1 import check_entry

NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
EPOCH=int(NOW.timestamp())
ENTRY_OPEN=EPOCH-300
def series(step,n=40,base=100):
    latest=(EPOCH-step)//step*step
    start=latest-(n-1)*step
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
             patch("src.okx_entry_evidence_gate_v1.chronological_break",return_value={"kind":"bullish_shift_candidate"}),\
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
             patch("src.okx_entry_evidence_gate_v1.chronological_break",return_value={"kind":"bullish_shift_candidate"}),\
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
             patch("src.okx_entry_evidence_gate_v1.chronological_break",return_value={"kind":"bullish_shift_candidate"}),\
             patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[poi]):
            result=evaluate(snap,observations(),NOW)
        self.assertEqual(result["paper_entries"],[])
    def test_missing_latest_candle_no_backdated_entry(self):
        s=fixture()
        for tf in ("5m",):
            s["timeframes"][tf]["bars"].pop()
        self.assertEqual(evaluate(s,observations(),NOW)["paper_entries"],[])
    def test_chronological_break_real_bars(self):
        values=[16,17,20,17,15,13,15,16,18,15,13,11,13,16,19,17,15]
        bars=[{"t":300*(i+100),"o":x,"h":x+.2,"l":x-.2,"c":x} for i,x in enumerate(values)]
        e=chronological_break(bars,bars[11]["t"],bars[14]["t"],bars[16]["t"],"long")
        self.assertEqual(e["kind"],"bullish_shift_candidate")
        self.assertEqual(e["event_close_s"],bars[14]["t"]+300)
        self.assertIsNone(chronological_break(bars,bars[11]["t"],bars[14]["t"],bars[16]["t"],"short"))
        self.assertIsNone(chronological_break(bars,bars[11]["t"],bars[13]["t"],bars[16]["t"],"long"))
    def test_break_on_retest_not_allowed(self):
        values=[16,17,20,17,15,13,15,16,18,15,13,11,13,16,19]
        bars=[{"t":300*(i+100),"o":x,"h":x+.2,"l":x-.2,"c":x} for i,x in enumerate(values)]
        self.assertIsNone(chronological_break(bars,bars[11]["t"],bars[13]["t"],bars[14]["t"],"long"))
    def test_missing_break_denies_paper_entry(self):
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=qm()):
            r=evaluate(fixture(),observations(),NOW)
        self.assertEqual(r["paper_entries"],[])
        self.assertIn("no_directional_bos_or_shift_in_qm_sequence",r["reasons"])
    def test_ifvg_availability_uses_inversion_close(self):
        bars=series(3600)
        inv=bars[-3]["t"]
        z={"direction":"long","low":99,"high":101,"formed_at":bars[-5]["t"],"inverted_at":inv}
        with patch("src.okx_entry_evidence_gate_v1.scan_ifvg",return_value=[z]):
            zones=prior_poi_zones(bars,3600,inv+3600,"long")
        self.assertEqual(zones[-1]["available_at"],inv+3600)
    def test_real_ifvg_only_after_inversion_close(self):
        step=3600
        bars=[{"t":step*(100+i),"o":x,"h":x+1,"l":x-1,"c":x}
              for i,x in enumerate([100,103,106,108,98,97])]
        inv=bars[4]["t"]
        early=prior_poi_zones(bars,step,inv,"short")
        late=prior_poi_zones(bars,step,inv+step,"short")
        self.assertFalse(any(z["kind"]=="IFVG" for z in early))
        self.assertTrue(any(z["kind"]=="IFVG" and z["available_at"]==inv+step for z in late))
    def test_invalidated_htf_poi_excluded(self):
        bars=series(3600)
        formed=bars[-5]["t"]
        bars[-2].update({"o":97,"h":98,"l":96,"c":97})
        with patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[
                {"direction":"long","low":99,"high":101,"formed":formed}]):
            zones=prior_poi_zones(bars,3600,bars[-1]["t"],"long")
        self.assertFalse(any(z["kind"]=="FVG" for z in zones))
    def test_duplicate_zones_one_directional_entry(self):
        snap=fixture()
        pois=[{"direction":"long","low":99,"high":101,"formed":ENTRY_OPEN-20000},
              {"direction":"long","low":99.5,"high":101,"formed":ENTRY_OPEN-21000}]
        with patch("src.okx_entry_evidence_gate_v1.scan_qm",return_value=qm()),\
             patch("src.okx_entry_evidence_gate_v1.chronological_break",return_value={"kind":"bullish_shift_candidate"}),\
             patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=pois):
            r=evaluate(snap,observations(),NOW)
        self.assertEqual(len(r["paper_entries"]),1)
    def test_future_htf_bars_excluded(self):
        bars=series(3600)
        head=bars[-3]["t"]
        with patch("src.okx_entry_evidence_gate_v1.fvg_zones",return_value=[]) as f:
            prior_poi_zones(bars,3600,head,"long")
        self.assertTrue(all(b["t"]+3600<=head for b in f.call_args.args[0]))
    def test_fvg_is_not_arbitrary_rr_target(self):
        p=confirmed_pivots(fixture()["timeframes"]["1h"]["bars"],3600,"long",EPOCH)
        self.assertEqual(p[-1]["level"],115)

if __name__=="__main__":unittest.main()
