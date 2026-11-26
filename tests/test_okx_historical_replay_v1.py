import unittest
from unittest.mock import patch
from src.okx_historical_replay_v1 import replay,stamp,VENUE,STEPS
def fixture():
    end=14400*100
    frames={}
    for tf,step in STEPS.items():
        frames[tf]={"status":"ok","bars":[{"t":end-(60-i)*step,"o":100,"h":101,"l":99,"c":100} for i in range(60)]}
    return {"source":VENUE,"status":"verified","classification":"closed_futures_candles_research_only","collected_at_utc":stamp(end).isoformat(),"timeframes":frames}
class ReplayTests(unittest.TestCase):
    def test_empty_alerts_never_create_entries(self):
        r=replay(fixture(),[])
        self.assertEqual(r["bars_evaluated"],31)
        self.assertEqual(r["historical_hypotheses"],[])
        self.assertIsNone(r["statistics"]["3.0"]["win_rate"])
    def test_wrong_venue_fails(self):
        s=fixture();s["source"]="BingX"
        self.assertEqual(replay(s,[])["status"],"insufficient_data")
    def test_gap_fails(self):
        s=fixture();s["timeframes"]["5m"]["bars"].pop(10)
        self.assertEqual(replay(s,[])["status"],"insufficient_data")
    def test_prefixes_no_future_data(self):
        def fake(s,obs,now):
            for tf,f in s["timeframes"].items():
                self.assertTrue(all(b["t"]+STEPS[tf]<=now.timestamp() for b in f["bars"]))
            self.assertEqual(obs,[])
            return {"diagnostics":{},"reasons":[],"paper_entries":[]}
        with patch("src.okx_historical_replay_v1.gate",side_effect=fake):
            self.assertEqual(replay(fixture(),[])["bars_evaluated"],31)
    def test_late_receipt_excluded(self):
        s=fixture();t=s["timeframes"]["5m"]["bars"][-3]["t"]+300
        a={"symbol":"OKX:BTCUSDT.P","time_ms":t*1000,"received_at_utc":stamp(t+361).isoformat()}
        self.assertEqual(replay(s,[a])["alert_rejections"]["invalid_or_late_receipt"],1)
    def test_future_candle_rejected(self):
        s=fixture();s["collected_at_utc"]=stamp(14400*100-1).isoformat()
        self.assertEqual(replay(s,[])["status"],"insufficient_data")
