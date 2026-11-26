import copy
import datetime as dt
import unittest
from src.okx_setup_validator_v1 import evaluate_event,evaluate,TV_SYMBOL

NOW=dt.datetime(2026,11,26,13,50,tzinfo=dt.timezone.utc)
CLOSE=int(NOW.timestamp())-600
CLOSE=CLOSE//300*300
def event(symbol=TV_SYMBOL,name="m5_bullish_fvg"):
    return {"source":"btc-intelligence-tv-v2","event":name,"symbol":symbol,
      "timeframe":"5","time_ms":(CLOSE+300)*1000,"price":101.0,
      "level":100.0,"level_kind":"fvg_upper","volume":100.0}

def candles():
    bars=[
        {"t":CLOSE-600,"o":96,"h":99,"l":94,"c":97},
        {"t":CLOSE-300,"o":98,"h":100,"l":97,"c":99},
        {"t":CLOSE,"o":100,"h":103,"l":100,"c":101},
    ]
    return {"source":"OKX BTC-USDT-SWAP","status":"verified",
       "collected_at_utc":NOW.isoformat(),
       "timeframes":{"5m":{"status":"ok","bars":bars}}}

class OKXSetupValidatorTests(unittest.TestCase):
    def test_confirm_matching_closed_okx_fvg_but_not_trade(self):
        r=evaluate_event(event(),candles(),NOW)
        self.assertEqual(r["status"],"observed_not_trade")
        self.assertEqual(r["corroboration"],"three_candle_fvg_consistent")
        self.assertFalse(r["entry_confirmed"])
        self.assertFalse(r["eligible_for_trade_statistics"])
        self.assertIsNone(r["trade_signal"])
        for x in ("entry","stop_loss","take_profit","rr"):
            self.assertIsNone(r[x])
    def test_real_github_ingestion_metadata_is_allowed(self):
        e=event()
        e["received_at_utc"]=NOW.isoformat()
        r=evaluate_event(e,candles(),NOW)
        self.assertEqual(r["status"],"observed_not_trade")
        self.assertIsNone(r["trade_signal"])
    def test_unexpected_ingestion_field_still_rejected(self):
        e=event()
        e["received_at_utc"]=NOW.isoformat()
        e["order"]="buy"
        r=evaluate_event(e,candles(),NOW)
        self.assertIn("invalid_alert_schema",r["reasons"])
    def test_bingx_cannot_be_promoted_to_okx(self):
        r=evaluate_event(event("BINGX:BTCUSDT.P"),candles(),NOW)
        self.assertEqual(r["status"],"withheld")
        self.assertIn("venue_mismatch_not_okx",r["reasons"])
    def test_price_disagreement_blocks(self):
        e=event();e["price"]=103
        r=evaluate_event(e,candles(),NOW)
        self.assertIn("okx_price_mismatch",r["reasons"])
    def test_fvg_structure_requires_same_venue_ohlc_confirmation(self):
        c=candles();c["timeframes"]["5m"]["bars"][0]["h"]=100.5
        r=evaluate_event(event(),c,NOW)
        self.assertIn("unconfirmed_okx_fvg",r["reasons"])
    def test_unrelated_bos_not_independently_confirmed(self):
        e=event(name="m5_bullish_bos")
        e["level"]=100;e["level_kind"]="pivot_high"
        r=evaluate_event(e,candles(),NOW)
        self.assertEqual(r["corroboration"],"closed_candle_price_consistent_only")
        self.assertFalse(r["entry_confirmed"])
    def test_misaligned_candle_blocks(self):
        e=event();e["time_ms"]+=1000
        self.assertIn("alert_candle_unavailable_or_misaligned",evaluate_event(e,candles(),NOW)["reasons"])
    def test_stale_candle_snapshot_fails(self):
        c=candles();c["collected_at_utc"]=(NOW-dt.timedelta(minutes=30)).isoformat()
        self.assertIn("stale_okx_candle_snapshot",evaluate_event(event(),c,NOW)["reasons"])
    def test_old_alert_rejected_even_with_matching_history(self):
        r=evaluate_event(event(),candles(),NOW+dt.timedelta(hours=3))
        self.assertIn("stale_or_future_alert",r["reasons"])
    def test_duplicate_id_prevents_reappend(self):
        e=event();a=evaluate([e,e],candles(),now=NOW)
        self.assertEqual(len(a["records_to_append"]),1)
        b=evaluate([e],candles(),existing_ids={a["records_to_append"][0]["event_id"]},now=NOW)
        self.assertEqual(b["okx_observations_new"],0)
    def test_no_mixing_on_missing_okx(self):
        c=candles();c["source"]="BingX USD-M Perpetual BTC-USDT"
        self.assertIn("unverified_okx_futures_candles",evaluate_event(event(),c,NOW)["reasons"])
    def test_malformed_tv_event_never_journaled(self):
        e=event();e["level_kind"]="pdh"
        r=evaluate([e],candles(),now=NOW)
        self.assertEqual(r["records_to_append"],[])
        self.assertEqual(r["reason_counts"].get("invalid_alert_schema"),1)

if __name__=="__main__":unittest.main()
