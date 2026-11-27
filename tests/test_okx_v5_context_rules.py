import unittest
from src.okx_v5_context_rules import contextual_shift,inside_deviation,rr_band,confluence,trend_relation
class ContextTests(unittest.TestCase):
    def test_shift(self):
        prev=[dict(t=i,o=100,c=101,h=102,l=99) for i in range(20)]
        bar=dict(t=20,o=101,c=105,h=106,l=101)
        e=dict(direction="long",kind="POI",tf="4h",known_at=19,valid=True)
        self.assertTrue(contextual_shift("long",bar,prev,102,[e]))
        self.assertFalse(contextual_shift("long",bar,prev,102,[]))
        self.assertFalse(contextual_shift("long",bar,prev,102,[dict(e,known_at=21)]))
        self.assertFalse(contextual_shift("long",bar,prev,102,[dict(e,tf="5m")]))
    def test_deviation(self):
        a=dict(t=1,h=110,l=90)
        b=dict(t=2,h=105,l=95)
        self.assertEqual(inside_deviation(a,b,dict(t=3,h=111,l=99,c=105)),"short")
        self.assertEqual(inside_deviation(a,b,dict(t=3,h=102,l=89,c=95)),"long")
        self.assertIsNone(inside_deviation(a,b,dict(t=3,h=111,l=89,c=95)))
    def test_rr(self):
        self.assertIsNone(rr_band(.99))
        self.assertEqual([rr_band(x) for x in (1,2,3)],["1_to_2","2_to_3","3_plus"])
    def test_confluence(self):
        a=dict(verified=True,known_at=10,valid_until=20,side="long")
        self.assertEqual(confluence({"a":a,"b":dict(a,known_at=16),"c":None},15),dict(long=1,short=0,neutral=0,missing=2))
    def test_trend(self):
        self.assertEqual(trend_relation("short","bullish"),"countertrend_correction_candidate")
        self.assertEqual(trend_relation("long","bullish",True),"continuation_after_correction")
