import datetime as dt
import json
import unittest
from pathlib import Path
from src.okx_m15_structural_gate import qm_shifts, ob_zones, evaluate

def bars(values,step=900):
    return [{"t":(1000+i)*step,"o":x,"h":x+.5,"l":x-.5,"c":x} for i,x in enumerate(values)]

class M15GateTests(unittest.TestCase):
    def test_short_shift_prefix_invariant(self):
        seq=bars([100,105,110,105,100,95,100,110,115,110,105,100,94,93])
        early=qm_shifts(seq[:12])
        self.assertFalse(any(q["direction"]=="short" for q in early))
        full=qm_shifts(seq)
        short=[q for q in full if q["direction"]=="short"]
        self.assertEqual(len(short),1)
        self.assertEqual(short[0]["shift_close"],seq[12]["t"]+900)
        self.assertEqual(short[0]["neckline"],94.5)
        self.assertEqual(qm_shifts(seq[:13]),full)
    def test_wick_does_not_confirm_shift(self):
        seq=bars([100,105,110,105,100,95,100,110,115,110,105,100,96])
        seq[-1]["l"]=90
        self.assertFalse(any(q["direction"]=="short" for q in qm_shifts(seq)))
    def test_ob_available_only_after_break_close(self):
        seq=bars([100,101,102,103,95],14400)
        seq[-2]["o"]=101
        before=seq[-1]["t"]
        self.assertEqual(ob_zones(seq,14400,before,"short"),[])
        self.assertEqual(len(ob_zones(seq,14400,before+14400,"short")),1)
    def test_wrong_venue(self):
        self.assertEqual(evaluate({"source":"Binance"})["status"],"unavailable")
    def test_real_missed_short_replay_prefixes(self):
        f=Path(__file__).parent/"fixtures"/"okx_20261127_m15_regression.json"
        archive=json.loads(f.read_text())["snapshot"]
        start=int(dt.datetime(2026,11,27,13,0,tzinfo=dt.timezone.utc).timestamp())
        end=int(dt.datetime(2026,11,27,14,45,tzinfo=dt.timezone.utc).timestamp())
        results=[]
        for close in range(start,end+1,300):
            now=dt.datetime.fromtimestamp(close+30,dt.timezone.utc)
            snap={**archive,"collected_at_utc":now.isoformat(),"timeframes":{}}
            for tf,step in (("5m",300),("15m",900),("1h",3600),("4h",14400)):
                source=archive["timeframes"][tf]
                snap["timeframes"][tf]={"status":"ok","bars":[b for b in source["bars"] if b["t"]+step<=close]}
            r=evaluate(snap,now)
            self.assertEqual(r["status"],"observed")
            for q in r["shifts"]:
                self.assertLessEqual(q["shift_close"],close)
            for p in r["structural_research"]:
                self.assertEqual(p["entry_close_utc"],close)
                self.assertLess(p["shift_close_utc"],close)
            if r["shifts"] or r["structural_research"]:
                results.append({"close":close,"shifts":r["shifts"],"candidates":r["structural_research"]})
        print("M15_REAL_REPLAY",json.dumps(results,separators=(",",":")),flush=True)

if __name__=="__main__":unittest.main()
