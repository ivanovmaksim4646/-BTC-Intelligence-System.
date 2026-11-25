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

if __name__ == "__main__":
    unittest.main()
