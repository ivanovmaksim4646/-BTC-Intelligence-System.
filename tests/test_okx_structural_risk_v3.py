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

    def test_managed_fta_distinct_from_tp(self):
        r=plan("long",100,99,[{"low":101,"high":102,"direction":"short","kind":"OB"}],[106,110],separate_fta=True)
        self.assertEqual(r["status"],"paper_candidate")
        self.assertEqual(r["fta"],101)
        self.assertEqual(r["take_profit"],106)
        self.assertEqual(r["fta_zone"]["high"],102)
    def test_managed_short_nearest_liquidity_not_cherry_picked(self):
        r=plan("short",100,101,[{"low":98,"high":99,"direction":"long","kind":"FVG"}],[98,90],separate_fta=True)
        self.assertEqual(r["fta"],99)
        self.assertEqual(r["take_profit"],98)
        self.assertEqual(r["status"],"withheld")
    def test_managed_no_final_liquidity(self):
        r=plan("long",100,99,[{"low":101,"high":102,"direction":"short","kind":"FVG"}],[],separate_fta=True)
        self.assertEqual(r["reason"],"no_verified_final_liquidity")
