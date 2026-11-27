import unittest,datetime as dt
from src.okx_futures_candles import collect,INTERVALS
class SharedCloseTests(unittest.TestCase):
    def test_newer_candles_excluded(self):
        target=1795794900
        now=dt.datetime.fromtimestamp(target+310,dt.timezone.utc)
        def getter(tf):
            step=INTERVALS[tf][1];offset=345600 if tf=="1w" else 0
            end=(target-offset)//step*step+offset
            return [[str((end+i*step)*1000),"100","102","99","101","1","1","1","1"] for i in range(0,-35,-1)]
        out=collect(now,getter,target)
        self.assertEqual(out["status"],"verified")
        self.assertEqual(out["timeframes"]["5m"]["bars"][-1]["t"]+300,target)
    def test_missing_target_fails(self):
        target=1795794900
        now=dt.datetime.fromtimestamp(target+30,dt.timezone.utc)
        def getter(tf):
            step=INTERVALS[tf][1];offset=345600 if tf=="1w" else 0
            end=(target-offset)//step*step+offset
            return [[str((end+i*step)*1000),"100","102","99","101","1","1","1","1"] for i in range(-2,-36,-1)]
        self.assertEqual(collect(now,getter,target)["status"],"partial")
    def test_stale_cutoff(self):
        target=1795794900
        with self.assertRaises(ValueError):collect(dt.datetime.fromtimestamp(target+421,dt.timezone.utc),target_close_s=target)
