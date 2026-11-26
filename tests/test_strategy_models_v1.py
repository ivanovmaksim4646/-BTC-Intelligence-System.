import unittest
from src.strategy_models_v1 import scan_ifvg, scan_qm, combine

def bar(i,o,h,l,c):
    return {"t":i*300,"o":o,"h":h,"l":l,"c":c}

class TestStrategyModels(unittest.TestCase):
    def test_bullish_fvg_inverts_short_only_on_close(self):
        bars=[
            bar(0,100,102,98,101), bar(1,103,104,102,103),
            bar(2,105,108,105,107),  # bullish FVG 102..105
            bar(3,104,106,101,104),  # wick through only
            bar(4,103,105,99,101),   # CLOSE below lower edge
        ]
        matches=[x for x in scan_ifvg(bars) if x["formed_at"]==600]
        self.assertEqual(len(matches),1)
        self.assertEqual(matches[0]["direction"],"short")
        self.assertEqual(matches[0]["inverted_at"],1200)

    def test_no_inversion_from_wick_alone(self):
        bars=[bar(0,100,102,98,101),bar(1,103,104,102,103),bar(2,105,108,105,107),
              bar(3,103,106,99,104),bar(4,105,107,101,106)]
        self.assertFalse(any(x["formed_at"]==600 for x in scan_ifvg(bars)))

    def test_bearish_fvg_inverts_long(self):
        bars=[bar(0,100,103,98,99),bar(1,97,99,95,96),
              bar(2,94,95,92,93),bar(3,94,101,93,100)]
        self.assertTrue(any(x["direction"]=="long" and x["formed_at"]==600 for x in scan_ifvg(bars)))

    def test_qm_requires_real_swings_and_close_break(self):
        self.assertEqual(scan_qm([bar(i,100,101,99,100) for i in range(20)]),[])

    def test_incomplete_data_cannot_make_trade(self):
        out=combine({"source":"Kraken Spot","timeframes":{"H1":{"ifvg":[],"fvg":[]},"M5":{"qm":[]}}})
        self.assertIsNone(out["trade_signal"])
        self.assertFalse(out["models"]["HTF_POI_QM_LTF"]["entry_signal"])
        self.assertFalse(out["futures_verified"])

    def test_invalid_poi_not_accepted(self):
        out=combine({"timeframes":{"H1":{"fvg":[{"kind":"bullish_fvg","low":100,"high":90}]}}})
        self.assertEqual(out["htf_poi_fvg_candidates"]["H1"],[])

if __name__=="__main__":
    unittest.main()
