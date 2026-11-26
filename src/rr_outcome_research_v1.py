#!/usr/bin/env python3
"""Counterfactual RR outcome evaluator for confirmed, historical paper entries.

This computes outcomes only from CLOSED, chronological FUTURE candles after
an independently verified entry timestamp. It is not a backtest pipeline,
an executable target generator or a statement of live profitability.
Intrabar stop+target simultaneous hits are ambiguous and withheld.
Fees/slippage are measured as a pessimistic estimated R deduction.
"""
from __future__ import annotations
import math
from collections import defaultdict

TARGET_R=(1.0,1.5,2.0,2.5,3.0,4.0,5.0)

def valid_number(x):
    return type(x) in (int,float) and math.isfinite(x) and x>0

def compare_rr_paths(direction,entry,stop,entry_closed_ts,future_closed_bars,
                     *, target_rs=TARGET_R, total_cost_bps=14):
    """Stop/target first touch using OHLC after entry candle close.

    Returns observations at proposed fixed-R exit levels ONLY for comparative
    research. It does not replace the independently verified liquidity target
    prerequisite in the live or paper Risk Engine.
    """
    if direction not in ("long","short") or not valid_number(entry) or not valid_number(stop):
        raise ValueError("invalid direction or prices")
    if not ((stop<entry) if direction=="long" else (stop>entry)):
        raise ValueError("stop must be adverse")
    if type(entry_closed_ts) not in (int,float) or not math.isfinite(entry_closed_ts):
        raise ValueError("invalid entry time")
    if type(total_cost_bps) not in (int,float) or not math.isfinite(total_cost_bps) or total_cost_bps<0:
        raise ValueError("invalid costs")
    if not isinstance(future_closed_bars,list):
        raise ValueError("requires closed OHLC bars")
    levels=tuple(target_rs)
    if not levels or any(type(r) not in (int,float) or not math.isfinite(r) or r<=0 for r in levels):
        raise ValueError("invalid RR levels")
    if len(set(levels))!=len(levels):
        raise ValueError("duplicate RR level")
    dist=abs(entry-stop)
    ordered=[]
    last_t=entry_closed_ts
    for b in future_closed_bars:
        if not isinstance(b,dict) or b.get("closed") is not True:
            raise ValueError("unconfirmed candle")
        t=b.get("t")
        if type(t) not in (int,float) or not math.isfinite(t) or t<=last_t:
            raise ValueError("not strictly later closed candles")
        o,h,l,c=(b.get(x) for x in ("o","h","l","c"))
        if not all(valid_number(x) for x in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError("invalid future candle")
        last_t=t
        ordered.append(b)
    outcomes={}
    for rr in levels:
        target=entry+rr*dist if direction=="long" else entry-rr*dist
        if target<=0:
            outcomes[str(rr)]={"status":"invalid_target_geometry","net_r":None}
            continue
        result={"status":"unresolved","net_r":None,"hit_time":None,
                "counterfactual_target":round(target,8)}
        for b in ordered:
            stop_hit=(b["l"]<=stop if direction=="long" else b["h"]>=stop)
            target_hit=(b["h"]>=target if direction=="long" else b["l"]<=target)
            if stop_hit and target_hit:
                result.update({"status":"ambiguous_same_candle","hit_time":b["t"]})
                break
            if stop_hit or target_hit:
                # Model level fills, not realistic gap/slippage fills.
                # Subtract assumed two-sided costs in R units.
                costs_r=(entry*total_cost_bps/10000)/dist
                result.update({"status":"target_first" if target_hit else "stop_first",
                               "net_r":round((rr if target_hit else -1)-costs_r,6),
                               "hit_time":b["t"]})
                break
        outcomes[str(rr)]=result
    return {"classification":"closed_candle_counterfactual_only",
            "source":"same_venue_required_by_caller",
            "entry_closed_ts":entry_closed_ts,
            "cost_assumption_bps_round_trip":total_cost_bps,
            "candle_count":len(ordered),
            "outcomes":outcomes,"trade_signal":None}

def aggregate(records,rr_levels=TARGET_R):
    """Group only resolved outcomes; show censored sample counts explicitly."""
    result={}
    if not isinstance(records,list):raise ValueError("records required")
    for rr in rr_levels:
        key=str(rr)
        wins=[];losses=[];censored=0
        for record in records:
            outcome=((record.get("outcomes") or {}).get(key) or {}) if isinstance(record,dict) else {}
            status=outcome.get("status")
            value=outcome.get("net_r")
            if status in ("target_first","stop_first") and type(value) in (int,float) and math.isfinite(value):
                (wins if status=="target_first" else losses).append(value)
            else:censored+=1
        completed=wins+losses
        if not completed:
            result[key]={"completed":0,"censored":censored,"win_rate":None,
                         "expectancy_r":None,"profit_factor":None}
            continue
        gross_wins=sum(max(0,x) for x in completed)
        gross_losses=-sum(min(0,x) for x in completed)
        result[key]={"completed":len(completed),"censored":censored,
                     "win_rate":round(len(wins)/len(completed),6),
                     "expectancy_r":round(sum(completed)/len(completed),6),
                     "profit_factor":round(gross_wins/gross_losses,6) if gross_losses else None}
    return result
