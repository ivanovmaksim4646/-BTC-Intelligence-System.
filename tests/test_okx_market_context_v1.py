import datetime as dt
import copy
import unittest
from src.okx_market_context_v1 import evaluate,frame_context,confirmed_pivots,fresh_structure_break,SOURCE,TIMES
NOW=dt.datetime(2026,11,26,15,0,tzinfo=dt.timezone.utc)
TS=int(NOW.timestamp())
def candles():
    frames={}
    for tf,seconds in TIMES.items():
        end=(TS//seconds)*seconds
        bars=[]
        for i in range(40):
            t=end-(40-i)*seconds
            # Trend with non-monotone high/low to admit confirmed pivots.
            center=60000+i*3+[-30,0,45,0,-15,0][i%6]
            bars.append({"t":t,"o":center-3,"h":center+10,
                "l":center-10,"c":center+3})
        frames[tf]={"status":"ok","bars":bars}
    return {"source":SOURCE,"status":"verified",
       "classification":"closed_futures_candles_research_only",
       "collected_at_utc":NOW.isoformat(),"timeframes":frames}
def liquidity():
    # m5 last closed candle closes at 15:00; aligned by 1 second.
    return {"source":SOURCE,"classification":"multi_observation_liquidity_context_research_only",
       "generated_at_utc":NOW.isoformat(),"decision":"NO_TRADE","trade_signal":None,
       "observations":{"book":{"timestamp_ms":TS*1000-1000,
           "resting_imbalance":-.5,"bid_depth_btc":10.0,
           "ask_depth_btc":30.0},
           "open_interest_change":{"delta_btc":-3.0},
           "funding":{"rate_fraction":.00001},
           "mark_index_premium":{"premium_bps":-2.0},
           "wall_persistence":{"bid_zones":0,"ask_zones":0}}}
class MarketContextTests(unittest.TestCase):
    def test_confirmed_pivot_requires_right_bars(self):
        bars=[{"t":300*i,"o":99,"h":h,"l":100-h,"c":99}
              for i,h in enumerate([10,12,25,11,10,9,30])]
        highs,lows=confirmed_pivots(bars)
        self.assertIn(600,[x["t"] for x in highs])
        self.assertNotIn(1800,[x["t"] for x in highs])
    def test_integration_no_trade_and_same_venue_liquidity(self):
        r=evaluate(candles(),liquidity(),now=NOW)
        self.assertEqual(r["status"],"structure_and_sampled_liquidity")
        self.assertEqual(r["decision"],"NO_TRADE")
        self.assertIsNone(r["trade_signal"])
        self.assertFalse(r["execution_ready"])
        self.assertIsNone(r["complete_cvd_btc"])
        self.assertEqual(set(r["timeframes"]),set(TIMES))
        self.assertEqual(r["liquidity_context"]["resting_side"],"ask_heavier")
    def test_bingx_liquidity_does_not_merge(self):
        l=liquidity();l["source"]="BingX"
        r=evaluate(candles(),l,now=NOW)
        self.assertEqual(r["status"],"structure_only")
        self.assertIsNone(r["liquidity_context"])
    def test_future_lagging_candle_disqualifies(self):
        c=candles()
        c["timeframes"]["5m"]["bars"][-1]["t"]+=300
        r=evaluate(c,liquidity(),now=NOW)
        self.assertEqual(r["status"],"insufficient_data")
    def test_duplicate_bar_disqualifies(self):
        c=candles()
        a=c["timeframes"]["15m"]["bars"]
        a[-1]["t"]=a[-2]["t"]
        self.assertEqual(evaluate(c,liquidity(),now=NOW)["status"],"insufficient_data")
    def test_wrong_venue_candles_disqualifies(self):
        c=candles();c["source"]="BINGX:BTCUSDT.P"
        self.assertEqual(evaluate(c,liquidity(),now=NOW)["status"],"insufficient_data")
    def test_stale_candle_snapshot_disqualifies(self):
        c=candles();c["collected_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        self.assertEqual(evaluate(c,liquidity(),now=NOW)["status"],"insufficient_data")
    def test_stale_liquidity_ignored(self):
        l=liquidity();l["generated_at_utc"]=(NOW-dt.timedelta(minutes=17)).isoformat()
        self.assertEqual(evaluate(candles(),l,now=NOW)["status"],"structure_only")
    def test_invalid_book_imbalance_ignored(self):
        l=liquidity();l["observations"]["book"]["resting_imbalance"]=float("nan")
        self.assertIsNone(evaluate(candles(),l,now=NOW)["liquidity_context"])
    def test_stale_book_time_ignored(self):
        l=liquidity();l["observations"]["book"]["timestamp_ms"]=TS*1000-910000
        self.assertIsNone(evaluate(candles(),l,now=NOW)["liquidity_context"])
    def test_all_closed_candles_not_invented_break_of_structure(self):
        r=evaluate(candles(),liquidity(),now=NOW)
        self.assertTrue(all(v["fresh_bos_or_choch"] is None for v in r["timeframes"].values()))
    def break_bars(self,values):
        return [{"t":300*(i+100),"o":x,"h":x+0.2,"l":x-0.2,"c":x}
                for i,x in enumerate(values)]
    def test_bullish_bos_close_candidate(self):
        bars=self.break_bars([10,11,14,12,10,9,11,13,16,14,12,11,13,15,17])
        e=fresh_structure_break(bars,"5m")
        self.assertEqual(e["kind"],"bullish_bos_candidate")
        self.assertEqual(e["event_close_s"],bars[-1]["t"]+300)
        self.assertEqual(e["source"],SOURCE)
    def test_bearish_bos_close_candidate(self):
        bars=self.break_bars([30-x for x in [10,11,14,12,10,9,11,13,16,14,12,11,13,15,17]])
        self.assertEqual(fresh_structure_break(bars,"5m")["kind"],"bearish_bos_candidate")
    def test_bullish_choch_candidate(self):
        bars=self.break_bars([16,17,20,17,15,13,15,16,18,15,13,11,13,16,19])
        self.assertEqual(fresh_structure_break(bars,"5m")["kind"],"bullish_shift_candidate")
    def test_bearish_choch_candidate(self):
        bars=self.break_bars([40-x for x in [16,17,20,17,15,13,15,16,18,15,13,11,13,16,19]])
        self.assertEqual(fresh_structure_break(bars,"5m")["kind"],"bearish_shift_candidate")
    def test_wick_only_not_break(self):
        bars=self.break_bars([10,11,14,12,10,9,11,13,16,14,12,11,13,15,16])
        bars[-1]["h"]=18
        self.assertIsNone(fresh_structure_break(bars,"5m"))
    def test_recross_not_new_break(self):
        bars=self.break_bars([10,11,14,12,10,9,11,13,16,14,12,11,13,17,15,17])
        self.assertIsNone(fresh_structure_break(bars,"5m"))
    def test_historical_ifvg_remains_non_actionable(self):
        poi={"source":SOURCE,"classification":"futures_research_only",
             "evaluated_at_utc":NOW.isoformat(),"decision":"NO_TRADE",
             "ifvg":{"1h":[{"model":"IFVG","direction":"short",
                "status":"inverted_observation","low":60000,"high":60100,
                "inverted_at":TS-3600}]}}
        r=evaluate(candles(),liquidity(),poi,NOW)
        self.assertEqual(len(r["ifvg_context"]),1)
        self.assertEqual(r["ifvg_context"][0]["classification"],
                         "historical_ifvg_not_confirmed_live_poi")
        self.assertIsNone(r["trade_entry"])
    def test_ifvg_future_data_excluded(self):
        poi={"source":SOURCE,"classification":"futures_research_only",
             "evaluated_at_utc":NOW.isoformat(),"decision":"NO_TRADE",
             "ifvg":{"1h":[{"model":"IFVG","direction":"long",
                "status":"inverted_observation","low":60000,"high":60100,
                "inverted_at":TS+3600}]}}
        self.assertEqual(evaluate(candles(),liquidity(),poi,NOW)["ifvg_context"],[])
    def test_outdated_liquidity_never_informs_context_even_if_cached(self):
        l=liquidity();l["observations"]["book"]["timestamp_ms"]=TS*1000-450000
        r=evaluate(candles(),l,now=NOW)
        self.assertIsNone(r["liquidity_context"])
    def test_partial_frames_never_give_directional_forecast(self):
        c=candles();c["timeframes"]["1h"]["status"]="unavailable"
        r=evaluate(c,liquidity(),now=NOW)
        self.assertIsNone(r["directional_probability"])
        self.assertEqual(r["market_context"],"insufficient_data")
if __name__=="__main__":unittest.main()
