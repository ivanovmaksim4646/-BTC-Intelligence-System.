import unittest
from src.okx_history_365 import download
from src.okx_entry_evidence_gate_v1 import evaluate_historical,evaluate
class HistoryTests(unittest.TestCase):
    def test_pagination(self):
        def get(tf,after):
            return [[str(t*1000),"100","101","99","100","0","0","0","1"] for t in range(after//1000-300,max(-300,after//1000-900),-300) if t>=0]
        self.assertEqual(len(download("5m",0,1200,get)),4)
    def test_missing_history(self):
        with self.assertRaises(ValueError):download("5m",0,1200,lambda tf,after:[])
    def test_no_live_relaxation(self):
        from test_okx_entry_evidence_gate_v1 import fixture,NOW
        self.assertEqual(evaluate(fixture(),[],NOW)["paper_entries"],[])
        r=evaluate_historical(fixture(),NOW)
        self.assertFalse(r["policy"]["requires_TV_OKX_observation"])
        self.assertEqual(r["diagnostics"]["matching_tv_events"],0)
