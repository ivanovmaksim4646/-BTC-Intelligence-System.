import io
import json
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
from research.baseline import replay
from research.runner import inputs
from research.runner.replay import CONFIG, parameters


class ResearchRunnerTests(unittest.TestCase):
    def test_validated_config(self):
        cfg = json.loads(CONFIG.read_text())
        parameters(cfg)
        for change in ({"models":[]},{"models":["QM_M15"]*2},{"slippage_bps_per_side":float("nan")},
                       {"end_exclusive_utc":"2030-01-01"},{"risk_pct":5}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parameters(dict(cfg,**change))

    def test_archive_keys_match_pins(self):
        pins = json.loads(inputs.CHECKSUMS.read_text())
        self.assertEqual(inputs.archive_keys(date(2026,10,31), date(2026,11,3), pins),
                         ["2026-10","2026-11-01","2026-11-02"])

    def test_funding_coverage(self):
        first=inputs.stamp(date(2025,11,27))
        self.assertEqual(len(inputs.verified_funding(first,first+86400)),3)
        with self.assertRaises(ValueError):
            inputs.verified_funding(first-86400,first)

    def test_gap_and_duplicate_fail(self):
        start=date(2025,11,27)
        first=inputs.stamp(start)-30*86400
        rows=[replay.Bar(t,1,1,1,1,1,1) for t in range(first,first+31*86400,300)]
        for bad in (rows[:-1], rows[:1]+rows[:-1]):
            with patch.object(inputs,"archive_keys",return_value=["2025-11"]), patch.object(inputs,"archive_bytes"), patch.object(inputs,"parse_bars",return_value=bad):
                with self.assertRaisesRegex(ValueError,"duplicate"):
                    inputs.verified_bars(start,date(2025,11,28),Path("."))

    def test_wrong_taker_volume_fails(self):
        name="BTCUSDT-5m-2025-11.csv"
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,"w") as fd:
            fd.writestr(name,"0,4,5,2,3,10,299999,0,0,11\n")
        with self.assertRaisesRegex(ValueError,"taker"):
            list(inputs.parse_bars(raw.getvalue(),"2025-11",0,300))

    def test_ambiguous_bar_stops_first(self):
        book=replay.Book("QM_M15")
        s=replay.Setup(1,replay.Zone("OB",1,80,90,0),3600,0,90,98,100)
        book.order=s,replay.Level(1,130,"swing")
        book.execute(replay.Bar(300,100,140,88,120,1,.5),900,{})
        self.assertEqual([r["outcome"] for r in book.rows],["SL"])
        self.assertGreaterEqual(book.rows[0]["planned_RR"],2)

class ValidationTests(unittest.TestCase):
    def test_folds_are_disjoint_and_chronological(self):
        from research.runner.validation import bounds, DAY
        self.assertEqual(bounds(0,4*DAY,2,1),[(0,2*DAY,3*DAY),(DAY,3*DAY,4*DAY)])
        for lengths in [(0,1),(4,1)]:
            with self.assertRaises(ValueError):
                bounds(0,4*DAY,*lengths)

    def test_reviewed_examples_distinguish_missing_wrong_side_and_skip(self):
        from research.runner.validation import approved_examples
        ex=dict(id="synthetic-test",model="QM_M15",entry_utc="1970-01-01T00:05:00+00:00",
                direction="LONG",expected="entry",provenance="unit test")
        row=dict(model=ex["model"],entry_utc=ex["entry_utc"],d=1)
        compare=lambda example:approved_examples([example],[row],["QM_M15"],0,900)[0]["status"]
        self.assertEqual(compare(ex),"match")
        self.assertEqual(compare(dict(ex,direction="SHORT")),"mismatch")
        self.assertEqual(compare(dict(ex,direction="SHORT",expected="skip")),"match")
        self.assertEqual(compare(dict(ex,entry_utc="1970-01-02T00:05:00+00:00")),"outside_config")


class ConfirmedRuleIntegrationTests(unittest.TestCase):
    def test_confirmed_predicates(self):
        from research.runner.confirmed_filters import self_test
        self_test()

    def test_inside_bar_chart_without_retest(self):
        from tempfile import TemporaryDirectory
        from research.runner.charts import render
        bars=[replay.Bar(t,100,110,90,105,1,.5) for t in range(0,7200,300)]
        row=dict(model="IB_M15_market",d=1,entry_utc=replay.utc(3600),
                 poi_tf=3600,poi="OB",poi_lo=90,poi_hi=95,entry=100,
                 stop=89,target=125,retest_lo=100,retest_hi=100,
                 target_type="opposite_IB_boundary",planned_RR=2,
                 outcome="TP",exit_utc=replay.utc(3900),R=2,
                 evidence=dict(range_low=95,range_high=125,
                    shift=dict(close_utc=replay.utc(3600),close_price=100,
                               level=99,tf_seconds=900)))
        with TemporaryDirectory() as folder:
            path=Path(folder)/"entries.html"
            render(path,bars,[row])
            html=path.read_text()
            self.assertIn("Range low",html)
            self.assertIn("Range high",html)
            self.assertNotIn("Retest low",html)
            self.assertIn("час не записано",html)
            row["evidence"].update(touch_open_utc=replay.utc(2700),
                                   retest_close_utc=replay.utc(3300))
            render(path,bars,[row])
            self.assertIn("Retest low",path.read_text())
