#!/usr/bin/env python3
"""OKX BTC-USDT-SWAP Risk Engine v2 — venue-pure, paper-only.

Risk sizing is illustrative until OKX tick/lot/min-size/fee tier, liquidity
targets, retest execution evidence and backtesting are independently verified.
Never manufactures a target from an RR. Never emits an executable trade signal.
Do NOT treat manually asserted candidate evidence flags as independent proof.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
try:
    from src.risk_engine_v1 import calculate as calculate_v1
    from src.risk_engine_v1 import assess_snapshot as assess_v1
except ModuleNotFoundError:
    from risk_engine_v1 import calculate as calculate_v1
    from risk_engine_v1 import assess_snapshot as assess_v1

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-risk-engine-v2-okx.json"
VENUE="OKX BTC-USDT-SWAP"
MAX_RISK_FRACTION=0.01
MAX_LEVERAGE=5
MIN_RESEARCH_NET_RR=1.0
MAIN_WATCHLIST_NET_RR=2.0
RESEARCH_RR_THRESHOLDS=(1.0,1.5,2.0,2.5,3.0,4.0,5.0)

def calculate_paper(candidate, *, equity_usdt,
                    risk_fraction=MAX_RISK_FRACTION,leverage_cap=MAX_LEVERAGE,
                    stop_buffer_bps=3,entry_slippage_bps=2,
                    exit_slippage_bps=2,taker_fee_bps_per_side=5,now=None):
    """Safety envelope is strictly <=1% equity and <=5x notional leverage.

    Fee/slippage bps are scenarios, not verified account-specific fee tiers.
    Returns paper scenario ONLY; no market order, trading advice, or execution.
    """
    now=now or dt.datetime.now(dt.timezone.utc)
    if type(risk_fraction) not in (int,float) or not 0<risk_fraction<=MAX_RISK_FRACTION:
        return {"status":"withheld","classification":"paper_research_only",
                "reason":"risk_fraction_exceeds_one_percent_or_invalid",
                "entry_signal":False,"trade_signal":None}
    if type(leverage_cap) not in (int,float) or not 0<leverage_cap<=MAX_LEVERAGE:
        return {"status":"withheld","classification":"paper_research_only",
                "reason":"leverage_cap_exceeds_five_or_invalid",
                "entry_signal":False,"trade_signal":None}
    r=calculate_v1(candidate,equity_usdt=equity_usdt,risk_fraction=risk_fraction,
        leverage_cap=leverage_cap,stop_buffer_bps=stop_buffer_bps,
        entry_slippage_bps=entry_slippage_bps,exit_slippage_bps=exit_slippage_bps,
        taker_fee_bps_per_side=taker_fee_bps_per_side,now=now,venue=VENUE,
        min_net_rr=MIN_RESEARCH_NET_RR)
    r["venue"]=VENUE
    r["research_rr_thresholds"]=list(RESEARCH_RR_THRESHOLDS)
    r["min_research_rr_net"]=MIN_RESEARCH_NET_RR
    r["main_watchlist_rr_net"]=MAIN_WATCHLIST_NET_RR
    if r["status"]=="paper_scenario_only":
        r["rr_category"]=("main_watchlist_candidate" if r["rr_net_estimate"]>=MAIN_WATCHLIST_NET_RR
                          else "research_only")
        r["rr_classification"]="computed_net_of_assumed_fees_and_slippage"
        r["outcome"]="unobserved"
    else:
        r["rr_category"]=None
    r["risk_limit_fraction"]=risk_fraction
    r["execution_ready"]=False
    r["exchange_lot_tick_fee_verified"]=False
    r["evidence_status"]="candidate_flags_are_not_independent_market_proof"
    r["trade_signal"]=None
    r["entry_signal"]=False
    return r

def assess_snapshot(observations, candle_snapshot=None, now=None):
    """Integrate real OKX same-venue research but forbid auto-generated entries.

    The POI/QM feed contains historical observations, not independently
    validated current target, entry tick, and executable order evidence.
    """
    now=now or dt.datetime.now(dt.timezone.utc)
    r=assess_v1(observations,now=now,venue=VENUE)
    r["schema_version"]="2.0"
    r["classification"]="okx_risk_gate_research_only"
    r["execution_ready"]=False
    r["max_account_risk_fraction"]=MAX_RISK_FRACTION
    r["max_notional_leverage"]=MAX_LEVERAGE
    r["rr_policy"]={
        "research_net_rr_from":MIN_RESEARCH_NET_RR,
        "main_watchlist_net_rr_from":MAIN_WATCHLIST_NET_RR,
        "counterfactual_targets_r":list(RESEARCH_RR_THRESHOLDS),
        "outcomes_recorded":False,
        "selection_policy":"compare_realized_outcomes_after_data_validation",
        "target_policy":"no_target_fabrication; actual target needs verified opposing liquidity",
    }
    r["requires"]=[
        "same_venue_confirmed_retest_close",
        "independently_confirmed_opposing_liquidity_target_before_entry",
        "actual_OKX_contract_lot_tick_minimum_and_fee_schedule",
        "fresh_same_venue_orderflow_and_execution_slippage_evidence",
        "backtesting_and_forward_validation"
    ]
    def fresh_utc(value,window_minutes=15):
        try:
            t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
            return t.tzinfo is not None and dt.timedelta(0)<=now-t<=dt.timedelta(minutes=window_minutes)
        except (ValueError,TypeError,AttributeError):
            return False
    good_candles=(isinstance(candle_snapshot,dict)
        and candle_snapshot.get("source")==VENUE
        and candle_snapshot.get("status")=="verified"
        and fresh_utc(candle_snapshot.get("collected_at_utc"))
        and isinstance(candle_snapshot.get("timeframes"),dict)
        and all(isinstance(candle_snapshot["timeframes"].get(tf),dict)
          and candle_snapshot["timeframes"][tf].get("status")=="ok"
          and len(candle_snapshot["timeframes"][tf].get("bars") or [])>=30
          for tf in ("5m","15m","1h","4h","1d","1w")))
    r["okx_closed_candles_verified"]=good_candles
    r["trade_signal"]=None
    r["entry_signal"]=False
    r["decision"]="NO_TRADE"
    r["scenarios"]=[]
    if not good_candles:
        r["reasons"].append("missing_or_unverified_okx_futures_candles")
    if good_candles and not r["candidates_inspected"]:
        r["reasons"].append("no_live_confirmed_okx_qm_retest_and_independent_target")
    return r

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    r=assess_snapshot(read("BTC-okx-poi-qm-v1.json"),read("BTC-okx-futures-candles.json"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    t=OUT.with_suffix(".json.tmp")
    t.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    t.replace(OUT)
    print("OKX Risk Engine v2:",r["decision"],"closed candles",r["okx_closed_candles_verified"],
          "historical candidates",r["candidates_inspected"])

if __name__=="__main__":main()
