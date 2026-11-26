import unittest
from src.rr_outcome_research_v1 import compare_rr_paths,aggregate,TARGET_R

def bar(t,o,h,l,c):
    return {"t":t,"o":o,"h":h,"l":l,"c":c,"closed":True}

class RROutcomeTests(unittest.TestCase):
    def test_long_target_then_stop_separate_path(self):
        # Entry and SL established at time 100; no candle before 100 used.
        bars=[bar(200,100,121,99,118),bar(300,118,120,89,95)]
        r=compare_rr_paths("long",100,90,100,bars,total_cost_bps=10)
        self.assertEqual(r["outcomes"]["1.0"]["status"],"target_first")
        self.assertEqual(r["outcomes"]["2.0"]["status"],"target_first")
        self.assertEqual(r["outcomes"]["2.5"]["status"],"stop_first")
        self.assertEqual(r["outcomes"]["1.0"]["net_r"],0.99)
        self.assertIsNone(r["trade_signal"])
    def test_short_mirror(self):
        bars=[bar(200,100,101,79,80),bar(300,80,111,78,105)]
        r=compare_rr_paths("short",100,110,100,bars)
        self.assertEqual(r["outcomes"]["2.0"]["status"],"target_first")
        self.assertEqual(r["outcomes"]["3.0"]["status"],"stop_first")
    def test_ambiguous_same_candle_not_success(self):
        bars=[bar(200,100,131,89,100)]
        r=compare_rr_paths("long",100,90,100,bars)
        self.assertEqual(r["outcomes"]["2.0"]["status"],"ambiguous_same_candle")
        self.assertIsNone(r["outcomes"]["2.0"]["net_r"])
    def test_unresolved_not_win(self):
        r=compare_rr_paths("long",100,90,100,[bar(200,100,104,96,102)])
        self.assertEqual(r["outcomes"]["1.0"]["status"],"unresolved")
        self.assertIsNone(r["outcomes"]["1.0"]["net_r"])
    def test_lookahead_and_unclosed_rejected(self):
        for bars in ([bar(100,100,103,99,102)],
                     [{**bar(200,100,103,99,102),"closed":False}],
                     [bar(200,100,103,99,102),bar(200,101,104,100,102)]):
            with self.subTest(bars=bars),self.assertRaises(ValueError):
                compare_rr_paths("long",100,90,100,bars)
    def test_missing_and_invalid_stop_rejected(self):
        with self.assertRaises(ValueError):
            compare_rr_paths("long",100,101,100,[])
        with self.assertRaises(ValueError):
            compare_rr_paths("short",100,90,100,[])
    def test_no_fabricated_statistics(self):
        a=aggregate([])
        self.assertTrue(all(x["win_rate"] is None and x["expectancy_r"] is None
                            for x in a.values()))
    def test_aggregate_resolved_only(self):
        win=compare_rr_paths("long",100,90,100,[bar(200,100,123,99,122)])
        loss=compare_rr_paths("long",100,90,100,[bar(200,100,101,89,90)])
        pending=compare_rr_paths("long",100,90,100,[bar(200,100,102,98,101)])
        x=aggregate([win,loss,pending])
        self.assertEqual(x["2.0"]["completed"],2)
        self.assertEqual(x["2.0"]["censored"],1)
        self.assertEqual(x["2.0"]["win_rate"],0.5)
        self.assertIsNotNone(x["2.0"]["profit_factor"])
    def test_partial_loss_gap_warning(self):
        # No claim of realistic gap-aware fills is made; only assumed-level results.
        r=compare_rr_paths("long",100,90,100,[bar(200,85,87,82,84)])
        self.assertEqual(r["outcomes"]["1.0"]["status"],"stop_first")
    def test_rr_candidates(self):
        self.assertEqual(TARGET_R,(1.0,1.5,2.0,2.5,3.0,4.0,5.0))
        with self.assertRaises(ValueError):
            compare_rr_paths("long",100,90,100,[],target_rs=[2,2])
if __name__=="__main__":unittest.main()
