import datetime as dt
import importlib.util
import pathlib
import unittest

PATH = pathlib.Path(__file__).resolve().parents[1] / "src" / "setup_candidates.py"
SPEC = importlib.util.spec_from_file_location("setup_candidates", PATH)
sc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sc)
NOW = dt.datetime(2026, 11, 25, 14, 10, tzinfo=dt.timezone.utc)

def fixture(kind="bullish_shift_candidate", spot=.3, futures=.2, sweep=False):
    structure = {"status":"ok","latest_closed_utc":"2026-11-25T14:00:00Z",
                 "events":[{"kind":kind,"break_level":58000.0}]}
    if sweep:
        structure["events"].append({"kind":"sweep_low_reclaim_inside"})
    flow={"complete":True,"aligned":True,"window_end_utc":"2026-11-25T14:05:00Z",
          "observation":"both_aggressive_buy","spot_pressure":spot,"futures_pressure":futures}
    return structure, flow

class CandidateTests(unittest.TestCase):
    def test_long_without_sweep_is_allowed(self):
        result = sc.candidate_for("M5", *fixture(), NOW)
        self.assertEqual(result["status"], "watch_candidate")
        self.assertFalse(result["sweep_bonus"])
        self.assertFalse(result["entry_signal"])

    def test_sweep_optional_bonus(self):
        result = sc.candidate_for("M5", *fixture(sweep=True), NOW)
        self.assertTrue(result["sweep_bonus"])
        self.assertEqual(result["status"],"watch_candidate")

    def test_opposite_flow_does_not_confirm(self):
        result=sc.candidate_for("M5", *fixture(spot=-.3), NOW)
        self.assertEqual(result["status"],"unconfirmed")

    def test_short_with_downside_pressure(self):
        result=sc.candidate_for("M5", *fixture(kind="bearish_bos_candidate", spot=-.25, futures=-.3), NOW)
        self.assertEqual(result["direction"],"short")
        self.assertEqual(result["status"],"watch_candidate")

    def test_misaligned_close_rejected(self):
        a,b=fixture()
        b["window_end_utc"]="2026-11-25T14:10:00Z"
        self.assertEqual(sc.candidate_for("M5",a,b,NOW)["status"],"unavailable")

    def test_stale_rejected(self):
        a,b=fixture()
        self.assertEqual(sc.candidate_for("M5",a,b,NOW+dt.timedelta(minutes=30))["status"],"unavailable")

    def test_sweep_only_not_a_signal(self):
        a,b=fixture()
        a["events"]=[{"kind":"sweep_low_reclaim_inside"}]
        self.assertEqual(sc.candidate_for("M5",a,b,NOW)["status"],"no_structure_break")

    def test_stale_flow_no_candidate(self):
        a,b=fixture()
        result=sc.evaluate({"timeframes":{"M5":a}},
                           {"fresh":False,"timeframes":{"M5":b}},NOW)
        self.assertEqual(result["timeframes"]["M5"]["status"],"unavailable")
        self.assertIsNone(result["trade_signal"])

if __name__=="__main__":
    unittest.main()
