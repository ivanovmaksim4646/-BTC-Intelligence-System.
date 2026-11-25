import datetime as dt
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "structure.py"
SPEC = importlib.util.spec_from_file_location("structure", PATH)
st = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(st)

def bar(t, o, h, l, c):
    return {"t":t, "o":o, "h":h, "l":l, "c":c}

class StructureTests(unittest.TestCase):
    def test_drop_unclosed(self):
        rows = [[0,10,11,9,10],[300,10,12,9,11],[600,11,12,10,11]]
        self.assertEqual(len(st.closed_candles(rows, 700, 5)), 2)

    def test_inside_bar(self):
        bars=[bar(0,10,12,8,10),bar(300,10,13,7,11),
              bar(600,11,12,8,10),bar(900,10,11,9,10)]
        kinds=[x["kind"] for x in st.events_for(bars,"M5")["events"]]
        self.assertEqual(kinds,["inside_bar"])

    def test_sweep_high(self):
        bars=[bar(0,10,11,9,10),bar(300,10,12,8,11),
              bar(600,11,12,9,10),bar(900,10,13,9,11)]
        self.assertIn("sweep_high_reclaim_inside",[x["kind"] for x in st.events_for(bars,"M5")["events"]])

    def test_bullish_fvg(self):
        bars=[bar(0,10,11,9,10),bar(300,10,12,9,12),
              bar(600,12,14,12,13),bar(900,13,15,13,14)]
        self.assertTrue(any(x["kind"]=="bullish_fvg" for x in st.events_for(bars,"M5")["fvg"]))

    def test_fvg_filled_excluded(self):
        bars=[bar(0,10,11,9,10),bar(300,10,12,9,12),
              bar(600,12,14,12,13),bar(900,13,14,10,11)]
        self.assertFalse(any(x["formed_at"]==600 for x in st.events_for(bars,"M5")["fvg"]))

    def test_insufficient(self):
        self.assertEqual(st.events_for([bar(0,1,2,0,1)],"M5")["status"], "insufficient_candles")


    def test_bullish_shift_candidate_distinct_from_bos(self):
        highs = [10,12,15,12,11,12,13,11,10,11,12,15]
        lows  = [ 8, 9,10, 9, 7, 8, 9, 8, 6, 7, 8,10]
        closes= [ 9,11,12,10, 8,10,11, 9, 7,10,12,14]
        bars = [bar(i*300, closes[i], highs[i], lows[i], closes[i]) for i in range(12)]
        event = st.structural_shift(bars)
        self.assertIsNotNone(event)
        self.assertEqual(event["kind"], "bullish_shift_candidate")
        self.assertEqual(event["break_level"], 13)
        self.assertTrue(event["not_bos"])

    def test_bearish_shift_candidate(self):
        highs = [10,12,15,12,11,12,13,11,10,11,12,15]
        lows  = [ 8, 9,10, 9, 7, 8, 9, 8, 6, 7, 8,10]
        closes= [ 9,11,12,10, 8,10,11, 9, 7,10,12,14]
        # Reflect bearish trend into bullish trend, with a downward final break.
        bars = [bar(i*300, 30-closes[i], 30-lows[i], 30-highs[i], 30-closes[i]) for i in range(12)]
        event = st.structural_shift(bars)
        self.assertIsNotNone(event)
        self.assertEqual(event["kind"], "bearish_shift_candidate")
        self.assertEqual(event["break_level"], 17)

    def test_shift_requires_confirmed_swing_history(self):
        bars = [bar(i*300, 10, 11, 9, 10) for i in range(12)]
        self.assertIsNone(st.structural_shift(bars))

    def test_bearish_bos_after_lower_lows(self):
        highs = [10,12,15,12,11,12,13,11,10,11,12,11]
        lows  = [ 8, 9,10, 9, 7, 8, 9, 8, 6, 7, 8, 4]
        closes= [ 9,11,12,10, 8,10,11, 9, 7,10, 9, 5]
        bars = [bar(i*300, closes[i], highs[i], lows[i], closes[i]) for i in range(12)]
        bos = st.continuation_bos(bars)
        self.assertIsNotNone(bos)
        self.assertEqual(bos["kind"], "bearish_bos_candidate")
        self.assertEqual(bos["break_level"], 6)
        self.assertIsNone(st.structural_shift(bars))

    def test_bullish_bos_after_higher_highs(self):
        highs = [10,12,15,12,11,12,13,11,10,11,12,11]
        lows  = [ 8, 9,10, 9, 7, 8, 9, 8, 6, 7, 8, 4]
        closes= [ 9,11,12,10, 8,10,11, 9, 7,10, 9, 5]
        bars = [bar(i*300, 30-closes[i], 30-lows[i], 30-highs[i], 30-closes[i])
                for i in range(12)]
        bos = st.continuation_bos(bars)
        self.assertIsNotNone(bos)
        self.assertEqual(bos["kind"], "bullish_bos_candidate")
        self.assertEqual(bos["break_level"], 24)
        self.assertIsNone(st.structural_shift(bars))

    def test_wick_break_without_close_is_not_bos(self):
        highs = [10,12,15,12,11,12,13,11,10,11,12,11]
        lows  = [ 8, 9,10, 9, 7, 8, 9, 8, 6, 7, 8, 4]
        closes= [ 9,11,12,10, 8,10,11, 9, 7,10, 9, 7]
        bars = [bar(i*300, closes[i], highs[i], lows[i], closes[i]) for i in range(12)]
        self.assertIsNone(st.continuation_bos(bars))

    def test_no_bos_on_equal_swings(self):
        bars = [bar(i*300, 10, 11, 9, 10) for i in range(12)]
        self.assertIsNone(st.continuation_bos(bars))

if __name__ == "__main__":
    unittest.main()
