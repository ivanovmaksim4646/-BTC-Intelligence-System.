import unittest
from src.okx_context_research_v3 import trend,sweep,context,cohorts
class ContextTests(unittest.TestCase):
    def test_future_rejected(self):
        with self.assertRaises(ValueError):context({"entry_close_utc":300,"direction":"long"},{tf:[{"t":300}] for tf in ("5m","1h","4h","1d")})
    def test_empty_pivots(self):
        self.assertEqual(trend([]),"insufficient")
        self.assertFalse(sweep([],"long"))
    def test_cohorts(self):
        e={"context":{"h1_h4_aligned":True,"d1_aligned":False,"recent_m5_sweep":False}}
        self.assertEqual(cohorts([e])["h1_h4_alignment"],[e])
        self.assertEqual(cohorts([e])["alignment_and_sweep"],[])
