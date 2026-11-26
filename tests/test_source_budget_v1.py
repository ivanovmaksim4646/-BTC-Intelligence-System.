import unittest
from datetime import datetime,timezone,timedelta
from src.source_budget_v1 import evaluate
NOW=datetime(2026,11,26,13,35,tzinfo=timezone.utc)
def inputs():
    okx={"source":"OKX BTC-USDT-SWAP","collected_at_utc":NOW.isoformat(),
         "recent_trades":{"status":"observed","coverage":"limited_page_not_full_window"},
         "candles":{"status":"observed"},"open_interest":{"status":"snapshot_only"},
         "m5_cvd":None,"m5_delta_btc":None}
    bingx={"source":"BingX USD-M Perpetual BTC-USDT","collected_at_utc":NOW.isoformat(),
           "timeframes":{tf:{"status":"ok"} for tf in ("5m","15m","1h","4h","1d","1w")}}
    return okx,bingx
class BudgetGuardTests(unittest.TestCase):
    def test_partial_okx_does_not_retire_bingx(self):
        a,b=inputs();r=evaluate(a,b,NOW)
        self.assertEqual(r["decision"],"RETAIN_BINGX")
        self.assertFalse(r["switch_approved"])
        self.assertTrue(r["okx_features"]["live_rest_trade_page"])
        self.assertFalse(r["okx_features"]["complete_m5_delta"])
        self.assertTrue(all(r["bingx_features"].values()))
        self.assertIsNone(r["trade_signal"])
    def test_stale_venue_not_trusted(self):
        a,b=inputs();a["collected_at_utc"]=(NOW-timedelta(days=1)).isoformat()
        r=evaluate(a,b,NOW)
        self.assertFalse(r["okx_features"]["live_rest_trade_page"])
    def test_missing_data_fail_closed(self):
        r=evaluate(None,None,NOW)
        self.assertFalse(r["switch_approved"])
        self.assertEqual(r["decision"],"RETAIN_BINGX")
    def test_spoofed_okx_complete_cvd_cannot_bypass(self):
        a,b=inputs()
        a.update({"m5_cvd":999,"m5_delta_btc":999,"status":"fully_verified",
                  "closed_candles_5m_15m_1h_4h_1d_1w":True})
        r=evaluate(a,b,NOW)
        self.assertFalse(r["switch_approved"])
        self.assertFalse(r["okx_features"]["validated_okx_poi_qm_ifvg"])
if __name__=="__main__":unittest.main()
