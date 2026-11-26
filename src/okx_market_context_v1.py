#!/usr/bin/env python3
"""OKX-only closed-candle ICT structure + sampled liquidity descriptive context.

Uses confirmed pivots (two left and two RIGHT closed candles), avoiding
future look-ahead. Direction is descriptive HH/HL or LH/LL, not a setup.
Liquidity observations cannot independently validate BOS, trade execution,
absorption or complete CVD. No orders; decision always NO_TRADE.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-market-context-v1.json"
SOURCE="OKX BTC-USDT-SWAP"
TIMES={"5m":300,"15m":900,"1h":3600,"4h":14400}
LEFT=2
RIGHT=2
MAX_SOURCE_AGE_SECONDS=900
MAX_LIQUIDITY_AGE_SECONDS=900
CROSS_SKEW_SECONDS=120

def finite(x):
    return type(x) in (float,int) and math.isfinite(x)

def pos(x):
    return finite(x) and x>0

def age(value,now):
    try:
        x=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if x.tzinfo is None:return None
        return (now-x).total_seconds()
    except (ValueError,TypeError,AttributeError):return None

def valid_bar(b):
    return (isinstance(b,dict) and type(b.get("t")) is int and
       b["t"]>0 and all(pos(b.get(k)) for k in ("o","h","l","c")) and
       b["l"]<=min(b["o"],b["c"])<=max(b["o"],b["c"])<=b["h"])

def validate_frame(frame,seconds,now):
    if not isinstance(frame,dict) or frame.get("status")!="ok":return None
    bars=frame.get("bars")
    if not isinstance(bars,list) or len(bars)<30 or not all(valid_bar(b) for b in bars):
        return None
    if any((b["t"]%seconds!=0 or
            (i>0 and b["t"]-bars[i-1]["t"]!=seconds)) for i,b in enumerate(bars)):
        return None
    elapsed=now.timestamp()-(bars[-1]["t"]+seconds)
    if not 0<=elapsed<=seconds+120:return None
    return bars

def confirmed_pivots(bars):
    highs=[];lows=[]
    for i in range(LEFT,len(bars)-RIGHT):
        hi=bars[i]["h"];lo=bars[i]["l"]
        prior=bars[i-LEFT:i]
        future=bars[i+1:i+RIGHT+1]
        # Ties disqualify pivot to avoid ambiguous equal highs/lows.
        if all(hi>x["h"] for x in prior+future):
            highs.append({"t":bars[i]["t"],"price":hi})
        if all(lo<x["l"] for x in prior+future):
            lows.append({"t":bars[i]["t"],"price":lo})
    return highs,lows

def frame_context(bars,tf):
    highs,lows=confirmed_pivots(bars)
    state="mixed"
    if len(highs)>=2 and len(lows)>=2:
        hh=highs[-1]["price"]>highs[-2]["price"]
        hl=lows[-1]["price"]>lows[-2]["price"]
        lh=highs[-1]["price"]<highs[-2]["price"]
        ll=lows[-1]["price"]<lows[-2]["price"]
        if hh and hl:state="bullish"
        elif lh and ll:state="bearish"
    elif len(highs)<2 or len(lows)<2:
        state="insufficient_pivots"
    return {"timeframe":tf,"status":"observed","structure":state,
       "last_closed_candle_open_s":bars[-1]["t"],
       "last_closed_candle_close_s":bars[-1]["t"]+TIMES[tf],
       "last_close":bars[-1]["c"],
       "confirmed_swing_highs":highs[-2:],
       "confirmed_swing_lows":lows[-2:],
       "swing_confirmation_delay_bars":RIGHT,
       "fresh_bos_or_choch":None,
       "note":"HH/HL or LH/LL classification from two confirmed swing pairs; not BOS/CHOCH or an entry."}

def evaluate(candles,liquidity,poi=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone_required")
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":SOURCE,"classification":"closed_okx_swing_structure_plus_sampled_liquidity_research",
       "status":"insufficient_data","market_context":"insufficient_data",
       "timeframes":{tf:{"status":"unavailable","structure":"unavailable"} for tf in TIMES},
       "htf_structure":None,"ltf_structure":None,"liquidity_context":None,
       "alignment":"unavailable","observational_divergences":[],
       "ifvg_context":[],"warnings":[],
       "decision":"NO_TRADE","trade_signal":None,"trade_entry":None,
       "execution_ready":False,"directional_probability":None,
       "complete_cvd_btc":None,"complete_delta_btc":None,
       "confirmed_absorption":None,
       "note":"No independent entry, position direction or trade outcome follows from sampled liquidity."}
    verified=(isinstance(candles,dict) and candles.get("source")==SOURCE
        and candles.get("status")=="verified"
        and candles.get("classification")=="closed_futures_candles_research_only"
        and (lambda a:a is not None and 0<=a<=MAX_SOURCE_AGE_SECONDS)(
            age(candles.get("collected_at_utc"),now)))
    if not verified:
        result["warnings"].append("missing_or_stale_verified_okx_candles")
        return result
    for tf,seconds in TIMES.items():
        frame=(candles.get("timeframes") or {}).get(tf)
        bars=validate_frame(frame,seconds,now)
        if bars is None:
            result["warnings"].append("invalid_or_stale_closed_"+tf)
        else:result["timeframes"][tf]=frame_context(bars,tf)
    structures={tf:v["structure"] for tf,v in result["timeframes"].items()}
    if any(v["status"]!="observed" for v in result["timeframes"].values()):
        result["warnings"].append("incomplete_multiframe_structure")
        return result
    # HTF H1/H4 must agree for a directional higher-timeframe description.
    htf=structures["1h"] if structures["1h"]==structures["4h"] and structures["1h"] in ("bullish","bearish") else "mixed"
    # LTF M5/M15 must agree, independent of higher-timeframe outcome.
    ltf=structures["5m"] if structures["5m"]==structures["15m"] and structures["5m"] in ("bullish","bearish") else "mixed"
    result["htf_structure"]=htf
    result["ltf_structure"]=ltf
    result["market_context"]=htf if htf==ltf and htf in ("bullish","bearish") else "mixed"
    result["status"]="structure_only"
    # HTF disagreement with LTF is NOT a validated trade reversal, and
    # does not become a momentum divergence or entry.
    if htf in ("bullish","bearish") and ltf in ("bullish","bearish") and htf!=ltf:
        result["observational_divergences"].append("htf_ltf_swing_direction_disagreement")
    liq_valid=(isinstance(liquidity,dict) and liquidity.get("source")==SOURCE
        and liquidity.get("classification")=="multi_observation_liquidity_context_research_only"
        and liquidity.get("decision")=="NO_TRADE"
        and liquidity.get("trade_signal") is None
        and (lambda a:a is not None and 0<=a<=MAX_LIQUIDITY_AGE_SECONDS)(
            age(liquidity.get("generated_at_utc"),now)))
    if liq_valid:
        observations=liquidity.get("observations")
        book=observations.get("book") if isinstance(observations,dict) else None
        last_closed=result["timeframes"]["5m"]["last_closed_candle_close_s"]
        if (isinstance(book,dict) and type(book.get("timestamp_ms")) is int
            and 0<=now.timestamp()*1000-book["timestamp_ms"]<=MAX_LIQUIDITY_AGE_SECONDS*1000
            and abs(book["timestamp_ms"]/1000-last_closed)<=TIMES["5m"]+CROSS_SKEW_SECONDS
            and finite(book.get("resting_imbalance"))
            and -1<=book["resting_imbalance"]<=1
            and pos(book.get("bid_depth_btc")) and pos(book.get("ask_depth_btc"))):
            imbalance=book["resting_imbalance"]
            side="bid_heavier" if imbalance>0.15 else "ask_heavier" if imbalance<-.15 else "balanced"
            ctx={"book_timestamp_ms":book["timestamp_ms"],
                 "resting_side":side,"resting_imbalance":imbalance,
                 "open_interest_change":None,"funding":None,"premium":None,
                 "wall_persistence":None,
                 "not_executed_volume":True}
            for k,output in (("open_interest_change","open_interest_change"),
                  ("funding","funding"),("mark_index_premium","premium"),
                  ("wall_persistence","wall_persistence")):
                v=observations.get(k)
                if isinstance(v,dict):ctx[output]=v
            result["liquidity_context"]=ctx
            result["status"]="structure_and_sampled_liquidity"
            if ltf=="bullish" and side=="ask_heavier":
                result["observational_divergences"].append("bullish_swing_vs_ask_heavier_resting_book")
            if ltf=="bearish" and side=="bid_heavier":
                result["observational_divergences"].append("bearish_swing_vs_bid_heavier_resting_book")
            result["alignment"]="descriptive_only"
        else:result["warnings"].append("liquidity_book_stale_or_not_aligned_to_closed_m5")
    else:result["warnings"].append("missing_or_stale_okx_liquidity_intelligence")
    # Only verified historical IFVG descriptions; never promote them to a live POI
    # or use a pattern formed after the latest closed candle.
    if (isinstance(poi,dict) and poi.get("source")==SOURCE
        and poi.get("classification")=="futures_research_only"
        and poi.get("decision")=="NO_TRADE"
        and (lambda a:a is not None and 0<=a<=MAX_SOURCE_AGE_SECONDS)(
            age(poi.get("evaluated_at_utc"),now))):
        ifvg=poi.get("ifvg")
        if isinstance(ifvg,dict):
            close_s=result["timeframes"]["5m"]["last_closed_candle_close_s"]
            for tf in ("1h","4h"):
                for x in (ifvg.get(tf) or [])[-100:]:
                    if (isinstance(x,dict) and x.get("model")=="IFVG" and
                        x.get("status")=="inverted_observation" and
                        x.get("direction") in ("long","short") and
                        pos(x.get("low")) and pos(x.get("high")) and x["low"]<=x["high"]
                        and type(x.get("inverted_at")) is int and x["inverted_at"]<close_s):
                        result["ifvg_context"].append({"tf":tf,"direction":x["direction"],
                           "low":x["low"],"high":x["high"],
                           "inverted_at":x["inverted_at"],
                           "classification":"historical_ifvg_not_confirmed_live_poi"})
            result["ifvg_context"]=result["ifvg_context"][-12:]
    return result

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError,UnicodeError):return {}
    r=evaluate(read("BTC-okx-futures-candles.json"),
        read("BTC-okx-liquidity-intelligence-v1.json"),
        read("BTC-okx-poi-qm-v1.json"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    t=OUT.with_suffix(".json.tmp")
    t.write_text(json.dumps(r,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(OUT)
    print("OKX MARKET CONTEXT",r["status"],r["market_context"],
          "H1/H4",r["htf_structure"],"M5/M15",r["ltf_structure"],
          "liq",r["liquidity_context"] is not None,"warnings",r["warnings"])
if __name__=="__main__":main()
