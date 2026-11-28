import copy
import csv
import io
import json
import tempfile
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
