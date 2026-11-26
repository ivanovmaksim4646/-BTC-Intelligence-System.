#!/usr/bin/env python3
"""BTC Risk Engine v1: fail-closed, *paper-only* risk arithmetic.

Entry = independently evidenced, CLOSED BingX retest-candle close.
SL = evidenced QM head extreme, optionally outward-buffered in basis points.
TP = independently evidenced same-venue opposing liquidity level, NEVER
manufactured as an arbitrary multiple of risk to obtain RR >= 3.
Requires explicitly confirmed candidate structure, source, timestamps and
realistic slippage/fees assumptions. A passing example is NOT an order signal.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
VENUE = "BingX USD-M Perpetual BTC-USDT"

def finite_positive(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0

def epoch(v):
    if type(v) not in (int,float) or not math.isfinite(v):
        return None
    try:
        return dt.datetime.fromtimestamp(v, tz=dt.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None

def result(reason):
    return {
        "status": "withheld",
        "classification": "paper_research_only",
        "reason": reason,
        "entry_signal": False,
        "trade_signal": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "rr_gross": None,
        "rr_net_estimate": None,
        "position_btc": None,
        "notional_usdt": None,
        "leverage": None,
    }

def calculate(candidate, *, equity_usdt, risk_fraction=0.01,
              leverage_cap=5, stop_buffer_bps=3,
              entry_slippage_bps=2, exit_slippage_bps=2,
              taker_fee_bps_per_side=5,
              now=None):
    """Explicit evidence contract, with conservative two-way cost adjustments.

    Target must be an actual pre-existing level with independently
    validated source and timestamp, not chosen from an RR requirement.
    """
    out = result("unverified_candidate")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("timezone-aware now required")
    if not isinstance(candidate, dict):
        return out
    if (candidate.get("source") != VENUE or
        candidate.get("model") != "HTF_POI_QM_LTF" or
        candidate.get("direction") not in ("long", "short") or
        candidate.get("poi_touch_verified") is not True or
        candidate.get("qm_retest_verified") is not True or
        candidate.get("futures_closed_candle_confirmed") is not True or
        candidate.get("target_validated") is not True or
        candidate.get("target_source") != VENUE or
        candidate.get("entry_price_source") != "closed_retest_candle" or
        candidate.get("stop_source") != "confirmed_qm_head" or
        candidate.get("target_kind") not in ("opposing_liquidity", "prior_confirmed_swing")):
        return out
    t = epoch(candidate.get("retest_candle_close_utc"))
    confirmed = epoch(candidate.get("target_confirmed_utc"))
    touched = epoch(candidate.get("poi_touch_utc"))
    head_at = epoch(candidate.get("qm_head_utc"))
    if (not t or not confirmed or not touched or not head_at or
        not touched < head_at < t or confirmed > t or
        not dt.timedelta(0) <= now - t <= dt.timedelta(minutes=15)):
        out["reason"] = "stale_future_or_out_of_order_evidence"
        return out
    entry = candidate.get("retest_close")
    head = candidate.get("qm_head_extreme")
    target = candidate.get("target_level")
    if not all(finite_positive(x) for x in (entry, head, target, equity_usdt)):
        out["reason"] = "invalid_prices_or_equity"
        return out
    if not all(type(v) in (float,int) and math.isfinite(v) and v>=0 for v in
               (stop_buffer_bps,entry_slippage_bps,exit_slippage_bps,taker_fee_bps_per_side)):
        out["reason"] = "invalid_cost_assumptions"
        return out
    if (type(risk_fraction) not in (int,float) or not 0<risk_fraction<=0.02
        or type(leverage_cap) not in (int,float) or not 0<leverage_cap<=20):
        out["reason"] = "invalid_risk_limits"
        return out
    direction = candidate["direction"]
    stop = head * (1-stop_buffer_bps/10000 if direction=="long" else 1+stop_buffer_bps/10000)
    if not ((stop<entry<target) if direction=="long" else (target<entry<stop)):
        out["reason"] = "invalid_entry_stop_target_order"
        return out
    # Conservatively worsen both entry and exit for taker fees + slippage.
    cost_in=(entry_slippage_bps+taker_fee_bps_per_side)/10000
    cost_out=(exit_slippage_bps+taker_fee_bps_per_side)/10000
    if direction=="long":
        buy=entry*(1+cost_in)
        loss_per_btc=buy-stop*(1-cost_out)
        gain_per_btc=target*(1-cost_out)-buy
    else:
        sell=entry*(1-cost_in)
        loss_per_btc=stop*(1+cost_out)-sell
        gain_per_btc=sell-target*(1+cost_out)
    if loss_per_btc<=0 or gain_per_btc<=0:
        out["reason"]="cost_adjusted_reward_not_positive"
        return out
    rr_gross=abs(target-entry)/abs(entry-stop)
    rr_net=gain_per_btc/loss_per_btc
    if rr_net<3:
        out["reason"]="rr_below_three_after_costs"
        return out
    max_risk=equity_usdt*risk_fraction
    risk_sized_btc=max_risk/loss_per_btc
    cap_btc=equity_usdt*leverage_cap/entry
    size=min(risk_sized_btc,cap_btc)
    if not finite_positive(size):
        out["reason"]="invalid_position_size"
        return out
    out.update({
        "status":"paper_scenario_only",
        "reason":"requires_backtesting_and_forward_validation",
        "entry":round(entry,8),
        "stop_loss":round(stop,8),
        "take_profit":round(target,8),
        "rr_gross":round(rr_gross,4),
        "rr_net_estimate":round(rr_net,4),
        "position_btc":round(size,8),
        "notional_usdt":round(entry*size,2),
        "risk_usdt_estimate":round(size*loss_per_btc,2),
        "reward_usdt_estimate":round(size*gain_per_btc,2),
        "leverage_cap":leverage_cap,
        "costs_assumed_bps":{"entry_slippage":entry_slippage_bps,
                             "exit_slippage":exit_slippage_bps,
                             "taker_fee_per_side":taker_fee_bps_per_side},
        "evidence":{"venue":VENUE,"model":candidate["model"],
                    "retest_close_utc":candidate["retest_candle_close_utc"],
                    "target_kind":candidate["target_kind"],
                    "target_confirmed_utc":candidate["target_confirmed_utc"]},
    })
    return out

def assess_snapshot(observations, now=None):
    """Current BingX research observations lack validated target & retest
    candle-close evidence. Never promote them to paper scenarios by inference.
    """
    now=now or dt.datetime.now(dt.timezone.utc)
    entries=observations.get("observations") if isinstance(observations,dict) else None
    evaluation={
        "schema_version":"1.0",
        "evaluated_at_utc":now.isoformat(),
        "classification":"risk_gate_research_only",
        "venue":VENUE,
        "decision":"NO_TRADE",
        "trade_signal":None,
        "entry_signal":False,
        "scenarios":[],
        "candidates_inspected":len(entries) if isinstance(entries,list) else 0,
        "reasons":[],
    }
    if not isinstance(observations,dict) or observations.get("source")!=VENUE:
        evaluation["reasons"].append("missing_or_wrong_venue")
        return evaluation
    stamp=observations.get("evaluated_at_utc")
    try:
        stamp=dt.datetime.fromisoformat(stamp.replace("Z","+00:00"))
    except (ValueError,AttributeError):
        stamp=None
    if (not stamp or stamp.utcoffset() is None or
        not dt.timedelta(0)<=now-stamp<=dt.timedelta(minutes=15)):
        evaluation["reasons"].append("stale_research_observations")
        return evaluation
    if not isinstance(entries,list) or not entries:
        evaluation["reasons"].append("no_confirmed_poi_qm_retest")
        return evaluation
    # No risk numbers without complete, directly sourced evidence.
    evaluation["reasons"].append("missing_evidenced_entry_and_independent_target")
    evaluation["reasons"].append("historical_sequence_is_not_a_live_entry")
    return evaluation

def main():
    try:
        snap=json.loads((DATA/"BTC-bingx-poi-qm-v1.json").read_text(encoding="utf-8"))
    except (OSError,ValueError):
        snap={}
    out=assess_snapshot(snap)
    path=DATA/"BTC-risk-engine-v1.json"
    temp=path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    temp.replace(path)
    print("Risk Engine v1:",out["decision"],"candidates",out["candidates_inspected"])

if __name__=="__main__":
    main()
