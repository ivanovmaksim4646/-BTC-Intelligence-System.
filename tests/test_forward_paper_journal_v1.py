import unittest,datetime as dt
from src.forward_paper_journal_v1 import admit,advance,stats,VENUE
NOW=dt.datetime(2026,11,26,12,tzinfo=dt.timezone.utc)
def preview():
    return {"source":VENUE,"classification":"paper_signal_preview_only","execution_enabled":False,"generated_at_utc":NOW.isoformat(),"decision":"LONG","paper_signal":{"direction":"long","paper_only":True,"entry":100,"stop_loss":99,"take_profit":104,"cost_bps":14,"entry_close_utc":int(NOW.timestamp())}}
class Tests(unittest.TestCase):
    def test_disabled(self):self.assertIsNone(admit(preview(),[],NOW))
    def test_risk_and_duplicate(self):
        r=admit(preview(),[],NOW,True)
        self.assertLessEqual(r["risk_usd"],10.000001)
        self.assertGreater(r["eligible_from"],NOW.timestamp())
        self.assertIsNone(admit(preview(),[r],NOW,True))
    def test_win(self):
        r=admit(preview(),[],NOW,True);t=r["eligible_from"]
        bars=[{"t":t,"o":100,"h":101,"l":99.5,"c":100},{"t":t+300,"o":100,"h":104,"l":100,"c":104}]
        result=advance(r,bars,NOW+dt.timedelta(minutes=15))
        self.assertEqual(result["status"],"win")
        self.assertGreater(result["r_multiple"],2)
        self.assertEqual(stats([result])["win_rate_pct"],100)
    def test_ambiguous(self):
        r=admit(preview(),[],NOW,True);t=r["eligible_from"]
        result=advance(r,[{"t":t,"o":100,"h":104,"l":99,"c":100}],NOW+dt.timedelta(minutes=10))
        self.assertEqual(result["status"],"censored_entry_bar")
        self.assertIsNone(stats([result])["win_rate_pct"])
