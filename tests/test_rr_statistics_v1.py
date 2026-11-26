import unittest
from src.rr_statistics_v1 import build,VENUE
from src.rr_outcome_research_v1 import compare_rr_paths
def bar(t,o,h,l,c):return {"t":t,"o":o,"h":h,"l":l,"c":c,"closed":True}
class StatisticsReportTests(unittest.TestCase):
    def test_empty_history_yields_null_statistics(self):
        r=build([])
        self.assertEqual(r["entry_count"],0)
        self.assertIsNone(r["by_rr"]["2.0"]["win_rate"])
        self.assertIsNone(r["by_rr"]["3.0"]["expectancy_r"])
        self.assertFalse(r["performance_verified"])
        self.assertIsNone(r["trade_signal"])
    def test_unverified_or_duplicate_rows_not_counted(self):
        observations=compare_rr_paths("long",100,90,100,[bar(200,100,124,99,120)])
        first={"entry_id":"historical-test-1","source":VENUE,
               "classification":"validated_closed_candle_counterfactual",
               "entry_provenance_verified":True,"future_bars_verified":True,
               "outcomes":observations["outcomes"]}
        invalid={**first,"entry_id":"historical-test-2","source":"BingX"}
        x=build([first,first,invalid,{"entry_id":"unknown"}])
        self.assertEqual(x["entry_count"],1)
        self.assertEqual(x["rejected_records"],3)
        self.assertEqual(x["by_rr"]["2.0"]["completed"],1)
        self.assertFalse(x["performance_verified"])
if __name__=="__main__":unittest.main()
