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

    def managed(self,direction="long"):
        p=preview()
        p["decision"]=direction.upper()
        p["paper_signal"].update(direction=direction,management="fta_or_ltf_shift_be_v1",fta=101 if direction=="long" else 99,episode_id="test-episode")
        if direction=="short":p["paper_signal"].update(stop_loss=101,take_profit=96)
        return p
    def test_fta_moves_stop_next_bar_and_be_costs(self):
        r=admit(self.managed(),[],NOW,True);t=r["eligible_from"]
        bars=[{"t":t,"o":100,"h":100.5,"l":99.5,"c":100.2},
              {"t":t+300,"o":100.2,"h":101.2,"l":99.8,"c":100.5},
              {"t":t+600,"o":100.5,"h":100.8,"l":99.9,"c":100}]
        active=advance(r,bars[:2],NOW+dt.timedelta(minutes=15))
        self.assertEqual(active["active_stop_loss"],100)
        self.assertEqual(active["stop_loss"],99)
        self.assertEqual(active["be_effective_from"],t+600)
        result=advance(active,bars,NOW+dt.timedelta(minutes=20))
        self.assertEqual(result["status"],"be")
        self.assertLess(result["pnl_usd"],0)
        self.assertEqual(stats([result])["be"],1)
        self.assertIsNone(stats([result])["win_rate_pct"])
        self.assertLess(stats([result])["equity_usd"],1000)
    def test_short_fta_and_gap_beyond_be(self):
        r=admit(self.managed("short"),[],NOW,True);t=r["eligible_from"]
        bars=[{"t":t,"o":100,"h":100.5,"l":99.5,"c":99.8},
              {"t":t+300,"o":99.8,"h":100.2,"l":98.8,"c":99.5},
              {"t":t+600,"o":100.3,"h":100.6,"l":100.1,"c":100.4}]
        result=advance(r,bars,NOW+dt.timedelta(minutes=20))
        self.assertEqual(result["status"],"loss")
        self.assertEqual(result["exit_price"],100.3)
    def test_pre_fill_fta_cancels(self):
        r=admit(self.managed(),[],NOW,True);t=r["eligible_from"]
        result=advance(r,[{"t":t,"o":100.5,"h":101.2,"l":100.4,"c":101}],NOW+dt.timedelta(minutes=10))
        self.assertEqual(result["status"],"cancelled")
        self.assertEqual(stats([result])["cancelled"],1)
    def test_same_bar_entry_and_fta_censored(self):
        r=admit(self.managed(),[],NOW,True);t=r["eligible_from"]
        result=advance(r,[{"t":t,"o":100,"h":101.2,"l":99.5,"c":101}],NOW+dt.timedelta(minutes=10))
        self.assertEqual(result["status"],"censored_entry_bar")
    def test_fta_cannot_retroactively_prevent_original_stop(self):
        r=admit(self.managed(),[],NOW,True);t=r["eligible_from"]
        bars=[{"t":t,"o":100,"h":100.5,"l":99.5,"c":100},
              {"t":t+300,"o":100,"h":101.2,"l":98.9,"c":100.5}]
        result=advance(r,bars,NOW+dt.timedelta(minutes=15))
        self.assertEqual(result["status"],"loss")
        self.assertEqual(result["exit_price"],99)
    def test_episode_duplicate_after_terminal_status(self):
        r=admit(self.managed(),[],NOW,True)
        r["status"]="cancelled"
        self.assertIsNone(admit(self.managed(),[r],NOW,True))

    def test_confirmed_favorable_shift_can_move_stop_before_fta(self):
        from unittest.mock import patch
        r=admit(self.managed(),[],NOW,True);t=r["eligible_from"]
        bars=[{"t":t,"o":100,"h":100.5,"l":99.5,"c":100.1},
              {"t":t+300,"o":100.1,"h":100.8,"l":100.05,"c":100.7}]
        with patch("src.forward_paper_journal_v1.favorable_shift",return_value=True):
            result=advance(r,bars,NOW+dt.timedelta(minutes=15))
        self.assertEqual(result["be_trigger"],"m5_shift")
        self.assertEqual(result["active_stop_loss"],100)
