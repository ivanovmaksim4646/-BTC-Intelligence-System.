import unittest
from src.okx_structural_risk_v3 import plan

class StructuralRiskTests(unittest.TestCase):
    def test_long_poi_stop(self):
        r=plan("long",100,99,[{"low":98,"high":99.5,"direction":"long","kind":"FVG"}],[106])
        self.assertLess(r["stop_loss"],98)
        self.assertEqual(r["status"],"paper_candidate")
    def test_fta_blocks_rr(self):
        r=plan("long",100,99,[{"low":101,"high":102,"direction":"short","kind":"OB"}],[110])
        self.assertEqual(r["take_profit"],101)
        self.assertEqual(r["status"],"withheld")
    def test_short(self):
        r=plan("short",100,101,[{"low":100.5,"high":102,"direction":"short","kind":"IFVG"}],[94])
        self.assertGreater(r["stop_loss"],102)
        self.assertEqual(r["status"],"paper_candidate")
    def test_no_target(self):
        self.assertEqual(plan("long",100,99,[],[])["status"],"withheld")
