#!/usr/bin/env python3
"""OKX sampled top-three resting wall price-zone persistence, research only.

No execution, no CVD, no inference of real fills/absorption/spoofing or wall
cancellation. Matches price zones in consecutive sampled snapshots only.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from src.okx_liquidity_history_v1 import normalize, SOURCE, MAX_COMPARE_GAP

DATA=Path(__file__).resolve().parents[1]/"data"
IN=DATA/"BTC-okx-liquidity-history-v1.jsonl"
OUT=DATA/"BTC-okx-wall-persistence-v1.json"
MIN_SAMPLES=3
MAX_SAMPLES=12
MAX_SAMPLE_GAP_SECONDS=10*60
MAX_LAST_SAMPLE_AGE_SECONDS=15*60
PRICE_TOLERANCE_BPS=0.5
MAX_ANCHOR_DRIFT_BPS=50

def valid_number(x):
    return type(x) in (float,int) and math.isfinite(x)

def matched(previous, current, anchor):
    """Match distinct wall price levels in strictly adjacent snapshots.

    Greedy globally-nearest pairs from candidate distances with one-to-one
    capacity. A wall's size may change; persistence concerns *presence* of a
    resting price zone, NOT persistence of individual orders.
    """
    tol=anchor*PRICE_TOLERANCE_BPS/10000
    candidates=[]
    for i,p in enumerate(previous):
        for j,c in enumerate(current):
            distance=abs(p["price"]-c["price"])
            if distance<=tol:
                candidates.append((distance,i,j))
    chosen=[];used_prev=set();used_cur=set()
    for distance,i,j in sorted(candidates):
        if i not in used_prev and j not in used_cur:
            chosen.append((i,j))
            used_prev.add(i);used_cur.add(j)
    return chosen

def analyze(rows,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone_required")
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":SOURCE,"classification":"sampled_top3_resting_price_zone_persistence_only",
       "status":"insufficient_history","samples_considered":0,
       "sample_first_ms":None,"sample_last_ms":None,
       "gaps_verified_continuous":False,
       "persistent_bid_zones":[],"persistent_ask_zones":[],
       "newly_visible_bid_zones":[],"newly_visible_ask_zones":[],
       "no_longer_top3_bid_zones":[],"no_longer_top3_ask_zones":[],
       "warnings":[],"complete_delta_btc":None,"complete_cvd_btc":None,
       "confirmed_absorption":None,"confirmed_spoofing":None,
       "liquidation_heatmap":None,"trade_signal":None,"entry_signal":False}
    try:hist=normalize(rows)
    except ValueError as exc:
        result["status"]="invalid_history"
        result["warnings"].append(str(exc));return result
    if not hist:
        result["warnings"].append("no_snapshots");return result
    last=hist[-1]
    age=(now.timestamp()*1000-last["book_timestamp_ms"])/1000
    if not 0<=age<=MAX_LAST_SAMPLE_AGE_SECONDS:
        result["status"]="stale_history"
        result["warnings"].append("last_snapshot_stale")
        return result
    # Longest valid contiguous-in-time suffix of latest <=12 independent
    # exchange-timestamp observations. Neither sampling nor this adjacency
    # establishes coverage of exchanges' intra-interval order changes.
    latest=[last]
    for older in reversed(hist[:-1]):
        gap=(latest[0]["book_timestamp_ms"]-older["book_timestamp_ms"])/1000
        if gap<=0 or gap>min(MAX_SAMPLE_GAP_SECONDS,MAX_COMPARE_GAP):
            result["warnings"].append("broken_snapshot_sequence")
            break
        latest.insert(0,older)
        if len(latest)>=MAX_SAMPLES:break
    result["samples_considered"]=len(latest)
    result["sample_first_ms"]=latest[0]["book_timestamp_ms"]
    result["sample_last_ms"]=last["book_timestamp_ms"]
    if len(latest)<MIN_SAMPLES:
        result["warnings"].append("need_three_consecutive_recent_snapshots")
        return result
    # Conservative common price-zone frame. Major mid-price drift makes old
    # top3 levels noncomparable to current best bid/ask.
    center=(last["best_bid"]+last["best_ask"])/2
    for row in latest:
        mid=(row["best_bid"]+row["best_ask"])/2
        if abs(mid-center)/center*10000>MAX_ANCHOR_DRIFT_BPS:
            result["status"]="noncomparable_price_regime"
            result["warnings"].append("market_moved_over_50bps_from_anchor")
            return result
    result["status"]="sampled_comparison_available"
    for side in ("bid","ask"):
        key=f"{side}_walls"
        # Chains track one matching price level across ALL consecutive
        # snapshots. No duplicate wall may be consumed by multiple chains.
        chains=[{"origin_price":w["price"],"price":w["price"],
                 "sizes_btc":[w["btc"]],"seen":1} for w in latest[0][key]]
        for row in latest[1:]:
            prev=[{"price":ch["price"]} for ch in chains]
            pairs=matched(prev,row[key],center)
            new_chains=[]
            for i,j in pairs:
                ch=chains[i]
                wall=row[key][j]
                new_chains.append({"origin_price":ch["origin_price"],
                    "price":wall["price"],
                    "sizes_btc":ch["sizes_btc"]+[wall["btc"]],
                    "seen":ch["seen"]+1})
            chains=new_chains
            if not chains:break
        stable=[]
        for ch in chains:
            if ch["seen"]==len(latest):
                stable.append({"last_price":ch["price"],
                    "first_price":ch["origin_price"],
                    "samples_seen":ch["seen"],
                    "first_observed_btc":ch["sizes_btc"][0],
                    "last_observed_btc":ch["sizes_btc"][-1],
                    "min_observed_btc":round(min(ch["sizes_btc"]),8),
                    "max_observed_btc":round(max(ch["sizes_btc"]),8),
                    "individual_order_identity_verified":False,
                    "intraperiod_persistence_verified":False})
        result[f"persistent_{side}_zones"]=sorted(stable,key=lambda x:-x["last_observed_btc"])
        recent=latest[-1][key]
        prev=latest[-2][key]
        pairs=matched(prev,recent,center)
        matched_prev={i for i,j in pairs}
        matched_curr={j for i,j in pairs}
        result[f"newly_visible_{side}_zones"]=[
            {"price":w["price"],"btc":w["btc"],"interpretation":"not_top3_at_prior_sample"}
            for j,w in enumerate(recent) if j not in matched_curr]
        result[f"no_longer_top3_{side}_zones"]=[
            {"price":w["price"],"btc_at_prior_sample":w["btc"],
             "interpretation":"not_top3_now_not_proof_of_cancel_or_fill"}
            for i,w in enumerate(prev) if i not in matched_prev]
    result["warnings"].append(
       "three_or_more_samples_do_not_verify_intraperiod_order_presence")
    result["warnings"].append(
       "top3_absence_cannot_distinguish_cancel_fill_or_falling_below_top3")
    return result

def main():
    old=[];bad=False
    if IN.exists():
        for line in IN.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            try:old.append(json.loads(line))
            except (TypeError,ValueError):bad=True
    report=analyze(old if not bad else [{"invalid":"json_line"}])
    if bad:report["warnings"].append("invalid_json_line_in_history")
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX WALL persistence",report["status"],"samples",
          report["samples_considered"],"persistent bid/ask",
          len(report["persistent_bid_zones"]),len(report["persistent_ask_zones"]))
if __name__=="__main__":main()
