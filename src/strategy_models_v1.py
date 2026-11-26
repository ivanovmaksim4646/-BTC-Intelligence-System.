#!/usr/bin/env python3
"""ICT-style IFVG and Quasimodo observations on CLOSED Kraken Spot candles only.

Not validated Binance/BingX Futures, not trade-entry signals. All indices are
historical and confirmation uses only bars available at that timestamp.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

HTF = ("H1", "H4", "D1", "W1")
LTF = ("M5", "M15")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "BTC-strategy-models-v1.json"

def price(x):
    return type(x) in (int, float) and 0 < x < 10000000

def scan_ifvg(bars, lookback=200):
    """An FVG inverts on the FIRST subsequent closed candle crossing its far edge.
    Retest is an observation only: revisit of original gap after the break.
    """
    if len(bars) < 4:
        return []
    results = []
    first = max(2, len(bars) - lookback)
    for i in range(first, len(bars) - 1):
        a, z = bars[i - 2], bars[i]
        if z["l"] > a["h"]:
            kind, lo, hi, direction = "bullish_fvg", a["h"], z["l"], "short"
        elif z["h"] < a["l"]:
            kind, lo, hi, direction = "bearish_fvg", z["h"], a["l"], "long"
        else:
            continue
        for j in range(i + 1, len(bars)):
            crossed = bars[j]["c"] < lo if direction == "short" else bars[j]["c"] > hi
            if crossed:
                retested = any(
                    b["h"] >= lo and b["l"] <= hi for b in bars[j + 1:]
                )
                results.append({
                    "model": "IFVG", "direction": direction,
                    "original_fvg": kind, "low": lo, "high": hi,
                    "formed_at": z["t"], "inverted_at": bars[j]["t"],
                    "retest_observed": retested,
                    "status": "inverted_observation",
                })
                break
    return results[-20:]

def _pivots(bars, left=2, right=2):
    events = []
    for i in range(left, len(bars) - right):
        window = bars[i-left:i+right+1]
        if all(bars[i]["h"] > b["h"] for k,b in enumerate(window) if k != left):
            events.append({"side":"H","i":i,"value":bars[i]["h"],"confirmed_i":i+right})
        if all(bars[i]["l"] < b["l"] for k,b in enumerate(window) if k != left):
            events.append({"side":"L","i":i,"value":bars[i]["l"],"confirmed_i":i+right})
    return sorted(events, key=lambda x:(x["i"],x["side"]))

def scan_qm(bars, left=2, right=2):
    """4-pivot structural QM candidate: H-L-HH-LL or L-H-LL-HH.
    A CLOSE beyond the intervening pivot must follow the second extreme.
    Shoulder-zone retest is descriptive, not an executable entry.
    """
    if len(bars) < 12:
        return []
    raw = _pivots(bars[:-1], left, right)
    pivots = []
    for p in raw:
        if pivots and p["side"] == pivots[-1]["side"]:
            if (p["value"] > pivots[-1]["value"] if p["side"] == "H"
                else p["value"] < pivots[-1]["value"]):
                pivots[-1] = p
        else:
            pivots.append(p)
    results = []
    for a,b,c,d in zip(pivots,pivots[1:],pivots[2:],pivots[3:]):
        if d["confirmed_i"] >= len(bars):
            continue
        if [x["side"] for x in (a,b,c,d)] == ["H","L","H","L"] and c["value"] > a["value"] and d["value"] < b["value"]:
            direction, shoulder, head, break_level = "short", a["value"], c["value"], b["value"]
            broken = any(q["c"] < break_level for q in bars[c["i"]+1:d["i"]+1])
        elif [x["side"] for x in (a,b,c,d)] == ["L","H","L","H"] and c["value"] < a["value"] and d["value"] > b["value"]:
            direction, shoulder, head, break_level = "long", a["value"], c["value"], b["value"]
            broken = any(q["c"] > break_level for q in bars[c["i"]+1:d["i"]+1])
        else:
            continue
        if not broken:
            continue
        results.append({
            "model":"QM", "direction":direction, "left_shoulder":shoulder,
            "head_extreme":head, "broken_level":break_level,
            "head_time":bars[c["i"]]["t"], "structural_extreme_time":bars[d["i"]]["t"],
            "status":"structure_candidate_only",
            "retest_confirmation":"not_evaluated",
        })
    return results[-10:]

def combine(structure):
    """Cross-timeframe POI+QM is withheld absent verified Futures and zone touch."""
    tfs = structure.get("timeframes") or {}
    ifvg = {tf: (tfs.get(tf) or {}).get("ifvg",[]) for tf in HTF}
    qm = {tf: (tfs.get(tf) or {}).get("qm",[]) for tf in LTF}
    poi = {}
    for tf in HTF:
        rec = tfs.get(tf) or {}
        poi[tf] = [
            {"kind":g["kind"],"low":g["low"],"high":g["high"],
             "formed_at":g.get("formed_at"),"mitigation":"unverified",
             "source":"Kraken Spot"}
            for g in rec.get("fvg",[])
            if g.get("kind") in ("bullish_fvg","bearish_fvg")
            and price(g.get("low")) and price(g.get("high")) and g["low"] < g["high"]
        ]
    return {
        "schema_version":"1.0", "classification":"research_observations_only",
        "source":structure.get("source"), "futures_verified":False,
        "ifvg_htf":ifvg, "htf_poi_fvg_candidates":poi, "qm_ltf":qm,
        "models":{
            "IFVG_H1_W1":{"status":"observations_only","entry_signal":False},
            "HTF_POI_QM_LTF":{"status":"awaiting_verified_futures_poi_touch_and_qm_retest","entry_signal":False}
        },
        "trade_signal":None,
        "notes":["Closed Kraken Spot candles only; no Binance/BingX Futures confirmation.",
                 "QM swing structure is a simplified rule set; pattern does not imply retest or trade.",
                 "IFVG inversion requires a later candle close beyond far FVG boundary.",
                 "HTF FVG is not independently validated as an unmitigated POI.",
                 "No SL, TP, RR, entry or probabilities are generated."],
    }

def main():
    try:
        data=json.loads((ROOT/"data"/"BTC-structure-current.json").read_text(encoding="utf-8"))
    except (OSError,ValueError):
        data={}
    result=combine(data)
    OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("Strategy model observations updated, no trade signal")

if __name__=="__main__":
    main()
