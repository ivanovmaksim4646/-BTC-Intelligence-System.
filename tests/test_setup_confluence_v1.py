import datetime as dt
import unittest
from src.setup_confluence_v1 import evaluate

NOW = dt.datetime(2026, 11, 26, 12, 0, tzinfo=dt.timezone.utc)
EPOCH = lambda offset: int((NOW + dt.timedelta(seconds=offset)).timestamp())

def data():
    models = {
        "source": "Kraken Spot XBTUSD", "futures_verified": False,
        "ifvg_htf": {"H1": [{"direction": "long", "low": 90, "high": 93,
                             "inverted_at": EPOCH(-3900), "retest_observed": True}]},
        "htf_poi_fvg_candidates": {"H1": [{"kind": "bullish_fvg", "low": 92,
                                             "high": 95}]},
        "qm_ltf": {"M5": [{"direction": "long", "left_shoulder": 94,
                           "head_extreme": 89,
                           "structural_extreme_time": EPOCH(-900)}]}}
    report = {
        "report_data_status": "ready", "collected_at_utc": "2026-11-26T11:59:00Z",
        "order_flow": {"M5": {"coverage": {"spot": "complete", "futures": "complete"},
                               "spot_delta": 12, "futures_delta": 8}},
        "open_interest": {"source_time_utc": "2026-11-26T11:59:10Z",
                          "value": 2000, "change": {"H1": 20}}}
    structure = {"source": "Kraken Spot XBTUSD",
                 "collected_at_utc": "2026-11-26T11:59:30Z"}
    return models, report, structure

class ConfluenceTests(unittest.TestCase):
    def test_combines_context_without_fake_trade(self):
        out = evaluate(*data(), now=NOW)
        self.assertEqual(out["decision"], "NO_TRADE")
        self.assertIsNone(out["entry"])
        self.assertIsNone(out["stop_loss"])
        self.assertIsNone(out["take_profit"])
        self.assertIsNone(out["rr"])
        self.assertTrue(out["models"]["IFVG_H1_W1"]["observations"])
        self.assertTrue(out["models"]["HTF_POI_QM_LTF"]["observations"])
        self.assertFalse(out["models"]["HTF_POI_QM_LTF"]["observations"][0]["poi_touch_verified"])

    def test_partial_spot_data_blocks_all_candidates(self):
        m,r,s = data()
        r["order_flow"]["M5"]["coverage"]["spot"] = "partial"
        out = evaluate(m,r,s,now=NOW)
        self.assertIn("incomplete_m5_spot_or_futures_flow",out["reasons"])
        self.assertEqual(out["models"]["IFVG_H1_W1"]["status"],"unavailable")

    def test_stale_report_blocks(self):
        m,r,s = data()
        r["collected_at_utc"] = "2026-11-26T11:00:00Z"
        out=evaluate(m,r,s,now=NOW)
        self.assertEqual(out["models"]["HTF_POI_QM_LTF"]["status"],"unavailable")

    def test_stale_structure_blocks(self):
        m,r,s = data()
        s["collected_at_utc"] = "2026-11-26T11:25:00Z"
        self.assertIn("missing_stale_or_unsynchronized_inputs",evaluate(m,r,s,now=NOW)["reasons"])

    def test_opposite_delta_is_not_confirmed(self):
        m,r,s=data()
        r["order_flow"]["M5"]["futures_delta"]=-4
        out=evaluate(m,r,s,now=NOW)
        self.assertFalse(out["models"]["IFVG_H1_W1"]["observations"][0]["flow_aligned"])
        self.assertEqual(out["decision"],"NO_TRADE")

    def test_historical_qm_not_active(self):
        m,r,s=data()
        m["qm_ltf"]["M5"][0]["structural_extreme_time"] = EPOCH(-86400)
        out=evaluate(m,r,s,now=NOW)
        self.assertEqual(out["models"]["HTF_POI_QM_LTF"]["observations"],[])

    def test_historical_ifvg_not_active(self):
        m,r,s=data()
        m["ifvg_htf"]["H1"][0]["inverted_at"] = EPOCH(-200000)
        self.assertEqual(evaluate(m,r,s,now=NOW)["models"]["IFVG_H1_W1"]["observations"],[])

    def test_missing_oi_does_not_imply_increase(self):
        m,r,s=data()
        r["open_interest"]["source_time_utc"]="2026-11-25T00:00:00Z"
        out=evaluate(m,r,s,now=NOW)
        self.assertEqual(out["models"]["IFVG_H1_W1"]["observations"][0]["oi"]["direction"],"unavailable")
        self.assertIn("oi_missing_or_stale",out["reasons"])

    def test_unverified_source_blocks(self):
        m,r,s=data()
        m["futures_verified"]=True
        self.assertIn("source_or_provenance_unverified",evaluate(m,r,s,now=NOW)["reasons"])

if __name__=="__main__":
    unittest.main()
