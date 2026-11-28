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
