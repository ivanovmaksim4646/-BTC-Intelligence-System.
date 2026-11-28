import unittest
from research.baseline import replay as b
from research.runner.execution_v6 import ExecutionBook

class ExecutionTests(unittest.TestCase):
    def make(self,d=1):
        book=ExecutionBook("test",0,0)
        z=b.Zone("FVG",d,99,100,0) if d==1 else b.Zone("FVG",d,100,101,0)
        s=b.Setup(d,z,900,0,90 if d==1 else 110,z.lo,z.hi)
        target=b.Level(d,130 if d==1 else 70,"target")
        self.assertTrue(book.place_limit(s,target,z,900,300))
        return book,z
    def test_fill_both_directions(self):
        for d in (1,-1):
            book,z=self.make(d)
            bar=b.Bar(300,101,102,99,101,1,.5) if d==1 else b.Bar(300,99,101,98,99,1,.5)
            book.execute(bar,900,{})
            self.assertIsNotNone(book.pos)
            self.assertEqual(book.pos["entry"],100)
            self.assertIsNone(book.pending)
    def test_target_before_fill(self):
        book,_=self.make()
        book.execute(b.Bar(300,110,131,105,125,1,.5),900,{})
        self.assertIsNone(book.pos)
        self.assertEqual(book.limit_events[-1]["event"],"limit_target_before_fill")
    def test_ambiguous_fill_target(self):
        book,_=self.make()
        book.execute(b.Bar(300,110,131,99,125,1,.5),900,{})
        self.assertIsNone(book.pos)
        self.assertEqual(book.limit_events[-1]["event"],"limit_ambiguous_target_fill")
    def test_stop_first(self):
        book,_=self.make()
        book.execute(b.Bar(300,101,131,89,120,1,.5),900,{})
        self.assertEqual(book.rows[0]["outcome"],"SL")
    def test_fta_confirmation(self):
        book,z=self.make()
        book.execute(b.Bar(300,101,102,99,101,1,.5),1800,{})
        frames={tf:b.Frame(tf) for tf in b.FRAMES}
        frames[900].zones=[b.Zone("OB",-1,109,112,0)]
        bar=b.Bar(600,110,112,108,109,1,.5)
        book.after_close(bar,frames,{})
        self.assertEqual(book.pos["stop"],90)
        book.after_close(bar,frames,{900:-1})
        self.assertEqual(book.pos["stop"],100)
    def test_cancel_invalid_zone(self):
        book,_=self.make()
        frames={tf:b.Frame(tf) for tf in b.FRAMES}
        book.after_close(b.Bar(300,110,112,105,109,1,.5),frames,{})
        self.assertIsNone(book.pending)
        self.assertEqual(book.limit_events[-1]["event"],"limit_poi_invalidated")

    def test_structural_stop_after_shift(self):
        book,_=self.make()
        book.execute(b.Bar(300,101,102,99,101,1,.5),1800,{})
        frames={tf:b.Frame(tf) for tf in b.FRAMES}
        frames[900].zones=[b.Zone("OB",-1,109,112,0),b.Zone("FVG",1,104,105,600)]
        frames[900].last[-1]=b.Pivot(-1,103,600)
        bar=b.Bar(900,110,112,108,109,1,.5)
        book.after_close(bar,frames,{})
        self.assertEqual(book.pos["stop"],90)
        book.after_close(bar,frames,{900:-1})
        self.assertAlmostEqual(book.pos["stop"],102.9)
        self.assertEqual(book.pos["management"][-1]["reason"],"FTA_structural")

    def test_fta_invalidation_requires_new_retest(self):
        from research.runner.structure_v7 import fta_ready
        frames={tf:b.Frame(tf) for tf in b.FRAMES}
        zone=b.Zone("OB",-1,109,112,0)
        frames[900].zones=[zone]
        setup=b.Setup(1,b.Zone("FVG",1,99,100,0),900,0,90,99,100)
        self.assertFalse(fta_ready(setup,frames,b.Bar(0,110,111,109,110,1,.5),300))
        self.assertFalse(fta_ready(setup,frames,b.Bar(300,111,114,110,113,1,.5),600))
        frames[900].zones=[]
        self.assertFalse(fta_ready(setup,frames,b.Bar(600,113,114,112,113,1,.5),900))
        self.assertEqual(setup.time,900)
        self.assertTrue(fta_ready(setup,frames,b.Bar(900,113,114,99,101,1,.5),1200))

    def test_candidate_replay_smoke(self):
        from research.runner.structure_v7 import backtest
        data=[b.Bar(i*300,100,101,99,100,1,.5) for i in range(24)]
        books=backtest(data,{},24,start=0,end=7200)
        self.assertEqual(len(books),7)
