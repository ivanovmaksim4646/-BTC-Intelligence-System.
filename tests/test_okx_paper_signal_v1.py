import unittest
import datetime as dt
from src.okx_paper_signal_v1 import evaluate, VENUE
NOW=dt.datetime(2026,11,26,12,0,tzinfo=dt.timezone.utc)
def fixture():
    close=int(NOW.timestamp())-300
    c={"source":VENUE,"classification":"okx_confluence_research_only","generated_at_utc":NOW.isoformat(),"m5_close_s":close,"watch_direction":"long","missing":[],"conflicts":[]}
    g={"source":VENUE,"classification":"independently_reconstructed_okx_paper_hypotheses","generated_at_utc":NOW.isoformat(),"diagnostics":{"latest_m5_close_s":close},"structural_research":[{"direction":"long","entry_close_utc":close,"status":"paper_candidate","entry":100,"stop_loss":99,"take_profit":104,"cost_bps":14}]}
    return c,g
class Tests(unittest.TestCase):
    def test_complete(self):
        r=evaluate(*fixture(),now=NOW)
        self.assertEqual(r["decision"],"LONG")
        self.assertFalse(r["execution_enabled"])
    def test_missing(self):
        c,g=fixture();c["missing"]=["macro"]
        self.assertIsNone(evaluate(c,g,NOW)["paper_signal"])
    def test_low_rr(self):
        c,g=fixture();g["structural_research"][0]["take_profit"]=102
        self.assertEqual(evaluate(c,g,NOW)["decision"],"NO_TRADE")
    def test_mismatch(self):
        c,g=fixture();g["diagnostics"]["latest_m5_close_s"]-=300
        self.assertEqual(evaluate(c,g,NOW)["decision"],"NO_TRADE")

    def test_heatmap_optional_only(self):
        c,g=fixture();c["missing"]=["liquidation_heatmap"]
        r=evaluate(c,g,NOW)
        self.assertEqual(r["decision"],"LONG")
        self.assertIn("liquidation_heatmap_unavailable",r["warnings"])
        c["missing"].append("reconciled_flow_4h")
        self.assertEqual(evaluate(c,g,NOW)["decision"],"NO_TRADE")
