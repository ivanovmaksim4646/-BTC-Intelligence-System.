import datetime as dt
import unittest
from src.release_readiness_v1 import evaluate
NOW=dt.datetime(2026,11,26,19,30,tzinfo=dt.timezone.utc)
def flow(complete=True):
    windows={tf:{"required_m5":n,"reconciled_m5":n if complete else n-1,
        "coverage":"volume_reconciled_not_sequence_certified" if complete else "missing_or_unreconciled_m5"}
        for tf,n in (("5m",1),("15m",3),("1h",12),("4h",48))}
    return {"instruments":{i:{"rolling_windows":windows} for i in ("BTC-USDT","BTC-USDT-SWAP")},
        "results":[{"instrument":i,"volume_reconciled":complete} for i in ("BTC-USDT","BTC-USDT-SWAP")]}
def run(f=None,s=None,c=None,p=None,h=None):
    return evaluate(s if s is not None else {"recorded_at_utc":NOW.isoformat(),"event":"workflow_dispatch"},
        f if f is not None else flow(),c if c is not None else {"decision":"NO_TRADE"},
        p if p is not None else {"decision":"NO_TRADE","execution_enabled":False},
        h if h is not None else {"fully_operational_confirmed":True},NOW)
class ReadinessTests(unittest.TestCase):
    def test_no_auto_trade_even_when_reconciled(self):
        a=run()
        self.assertFalse(a["okx_full_trade_sequence_cvd_certified"])
        self.assertFalse(a["five_minute_dispatch_continuity_certified"])
        self.assertFalse(a["ready_for_autonomous_trading"])
    def test_missing_spot_window(self):
        a=run(f=flow(False))
        self.assertIn("BTC-USDT_latest_m5_not_volume_reconciled",a["issues"])
        self.assertIn("incomplete_reconciled_rolling_windows",a["issues"])
    def test_missing_scheduler(self):
        self.assertFalse(run(s={})["recent_scheduler_dispatch_observed"])
    def test_stale_scheduler(self):
        self.assertIn("scheduler_dispatch_missing_or_stale",run(s={"recorded_at_utc":"2026-11-26T18:00:00Z","event":"schedule"})["issues"])
    def test_future_scheduler(self):
        self.assertFalse(run(s={"recorded_at_utc":"2026-11-26T20:00:00Z","event":"schedule"})["recent_scheduler_dispatch_observed"])
    def test_conflicting_context(self):
        self.assertIn("confluence_missing_or_conflicting_evidence",run(c={"decision":"NO_TRADE","conflicts":["htf"]})["issues"])
    def test_execution_enabled(self):
        self.assertIn("paper_execution_safety_unverified",run(p={"decision":"NO_TRADE","execution_enabled":True})["issues"])
    def test_invalid_inputs(self):
        self.assertFalse(evaluate([],[],[],[],[],NOW)["ready_for_unqualified_live_reporting"])
    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):evaluate(None,None,None,None,None,dt.datetime(2026,11,26))
if __name__=="__main__":unittest.main()
