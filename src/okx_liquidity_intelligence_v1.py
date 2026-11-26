#!/usr/bin/env python3
"""OKX Liquidity Intelligence v1: read-only multi-source provenance gate.

All market measurements are already-produced public REST snapshots. An
observational divergence is NOT a trade signal, confidence, execution,
liquidation, absorption or complete delta/CVD claim. Output stays NO_TRADE.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-liquidity-intelligence-v1.json"
SOURCE="OKX BTC-USDT-SWAP"
MAX_AGE=15*60
MAX_CROSS_SKEW=120
MAX_OI_INTERVAL=20*60
MAX_BOOK_CHANGE_INTERVAL=20*60

def number(x):
    return type(x) in (float,int) and math.isfinite(x)

def positive(x):
    return number(x) and x>0

def age_iso(value,now):
    try:
        x=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if x.tzinfo is None:return None
        return (now-x).total_seconds()
    except (AttributeError,TypeError,ValueError):return None

def valid_source(obj,classification,now):
    if not isinstance(obj,dict) or obj.get("source")!=SOURCE or obj.get("classification")!=classification:
        return False
    age=age_iso(obj.get("generated_at_utc"),now)
    return age is not None and 0<=age<=MAX_AGE

def valid_exchange_ts(ts,now):
    return type(ts) is int and ts>0 and 0<=now.timestamp()*1000-ts<=MAX_AGE*1000

def align(a,b):
    return type(a) is int and type(b) is int and abs(a-b)<=MAX_CROSS_SKEW*1000

def evaluate(context,history,wall,flow,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone_required")
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":SOURCE,"classification":"multi_observation_liquidity_context_research_only",
       "status":"insufficient_evidence","decision":"NO_TRADE","trade_signal":None,
       "trade_entry":None,"execution_ready":False,
       "observations":{"book":None,"wall_persistence":None,
           "depth_change":None,"open_interest_change":None,"funding":None,
           "mark_index_premium":None},
       "context_tags":[],"warnings":[],
       "price_action_confirmation":None,"complete_delta_btc":None,
       "complete_cvd_btc":None,"liquidation_heatmap":None,
       "confirmed_absorption":None,"confirmed_spoofing":None,
       "note":"Resting book and OI snapshots are not executed trade flow; no inference of positions or direction."}
    ctx_ok=valid_source(context,"read_only_okx_snapshot_context",now)
    hist_ok=valid_source(history,"historical_resting_liquidity_sampling_only",now)
    wall_ok=valid_source(wall,"sampled_top3_resting_price_zone_persistence_only",now)
    flow_ok=valid_source(flow,"partial_rest_flow_audit_only",now)
    if not ctx_ok:result["warnings"].append("missing_or_stale_derivatives_context")
    if not hist_ok:result["warnings"].append("missing_or_stale_liquidity_history")
    if not wall_ok:result["warnings"].append("missing_or_stale_wall_persistence")
    if not flow_ok:result["warnings"].append("missing_or_stale_oi_coverage")
    if not ctx_ok:return result
    book=context.get("book")
    if not (isinstance(book,dict) and book.get("status")=="snapshot_only"
        and valid_exchange_ts(book.get("timestamp_ms"),now)
        and positive(book.get("bid_depth_btc")) and positive(book.get("ask_depth_btc"))
        and positive(book.get("best_bid")) and positive(book.get("best_ask"))
        and book["best_bid"]<book["best_ask"]
        and number(book.get("resting_imbalance"))
        and -1<=book["resting_imbalance"]<=1):
        result["warnings"].append("unverified_or_stale_book")
        return result
    book_ts=book["timestamp_ms"]
    result["observations"]["book"]={
        "timestamp_ms":book_ts,
        "bid_depth_btc":book["bid_depth_btc"],
        "ask_depth_btc":book["ask_depth_btc"],
        "resting_imbalance":book["resting_imbalance"],
        "sample_only":True}
    result["status"]="partial_observations"
    result["context_tags"].append("resting_book_snapshot_observed")
    if hist_ok:
        latest=history.get("latest")
        ch=history.get("change")
        if (isinstance(latest,dict) and latest.get("source")==SOURCE
            and latest.get("book_timestamp_ms")==book_ts
            and isinstance(ch,dict)
            and ch.get("status")=="two_sample_change_only"
            and ch.get("interval_fully_observed") is False
            and number(ch.get("elapsed_seconds"))
            and 0<ch["elapsed_seconds"]<=MAX_BOOK_CHANGE_INTERVAL
            and number(ch.get("bid_depth_change_btc"))
            and number(ch.get("ask_depth_change_btc"))
            and number(ch.get("imbalance_change"))):
            result["observations"]["depth_change"]={
                "elapsed_seconds":ch["elapsed_seconds"],
                "bid_depth_change_btc":ch["bid_depth_change_btc"],
                "ask_depth_change_btc":ch["ask_depth_change_btc"],
                "imbalance_change":ch["imbalance_change"],
                "interval_fully_observed":False}
            result["context_tags"].append("two_sample_depth_change_observed")
        else:result["warnings"].append("depth_comparison_missing_or_misaligned")
    if wall_ok:
        if (wall.get("status")=="sampled_comparison_available"
            and wall.get("gaps_verified_continuous") is False
            and wall.get("sample_last_ms")==book_ts
            and type(wall.get("samples_considered")) is int
            and wall["samples_considered"]>=3
            and isinstance(wall.get("persistent_bid_zones"),list)
            and isinstance(wall.get("persistent_ask_zones"),list)):
            bz=wall["persistent_bid_zones"];az=wall["persistent_ask_zones"]
            # Zones are only price-level repetitions. Their count is safe to
            # describe; do not promote them to independent trade evidence.
            if all(isinstance(z,dict) and type(z.get("samples_seen")) is int and
                   z["samples_seen"]==wall["samples_considered"] and
                   positive(z.get("last_price")) and positive(z.get("last_observed_btc"))
                   and z.get("intraperiod_persistence_verified") is False
                   for z in bz+az) and len(bz)<=3 and len(az)<=3:
                result["observations"]["wall_persistence"]={
                    "samples_considered":wall["samples_considered"],
                    "bid_zones":len(bz),"ask_zones":len(az),
                    "bid_zone_prices":[z["last_price"] for z in bz],
                    "ask_zone_prices":[z["last_price"] for z in az],
                    "intraperiod_persistence_verified":False}
                result["context_tags"].append("sampled_wall_zone_comparison_available")
            else:result["warnings"].append("wall_zone_validation_failed")
        else:result["warnings"].append("wall_persistence_missing_or_misaligned")
    f=context.get("funding")
    if isinstance(f,dict) and f.get("status")=="quoted_rate_snapshot":
        rate=f.get("rate_fraction")
        nt=f.get("next_funding_time_ms")
        if (number(rate) and abs(rate)<=.05 and type(nt) is int
            and 0<nt-now.timestamp()*1000<=48*3600*1000):
            result["observations"]["funding"]={
                "rate_fraction":rate,"next_funding_time_ms":nt,
                "classification":"quoted_not_realized"}
            result["context_tags"].append("quoted_funding_observed")
    p=context.get("mark_index")
    if isinstance(p,dict) and p.get("status")=="two_recent_public_snapshots":
        mt=p.get("mark_timestamp_ms");it=p.get("index_timestamp_ms")
        mark=p.get("mark_price");index=p.get("index_price")
        if (align(mt,it) and align(mt,book_ts)
            and valid_exchange_ts(mt,now) and valid_exchange_ts(it,now)
            and positive(mark) and positive(index)):
            result["observations"]["mark_index_premium"]={
                "mark_price":mark,"index_price":index,
                "premium_bps":round(10000*(mark-index)/index,6),
                "mark_timestamp_ms":mt,"index_timestamp_ms":it,
                "classification":"instantaneous_premium_not_expiry_basis"}
            result["context_tags"].append("mark_index_premium_observed")
        else:result["warnings"].append("mark_index_out_of_sync_with_book")
    if flow_ok:
        oc=flow.get("oi_change")
        latest_oi=flow.get("oi_snapshot")
        if (isinstance(oc,dict) and oc.get("status")=="two_verified_snapshots"
            and isinstance(latest_oi,dict)
            and oc.get("current_timestamp_ms")==latest_oi.get("timestamp_ms")
            and align(oc.get("current_timestamp_ms"),book_ts)
            and valid_exchange_ts(oc.get("current_timestamp_ms"),now)
            and number(oc.get("delta_btc"))
            and number(oc.get("delta_percent"))
            and positive(latest_oi.get("oi_btc"))
            and number(oc.get("elapsed_seconds"))
            and 0<oc["elapsed_seconds"]<=MAX_OI_INTERVAL
            and oc.get("limitation")=="not_continuous_intraperiod_OI"):
            result["observations"]["open_interest_change"]={
                "delta_btc":oc["delta_btc"],
                "delta_percent":oc["delta_percent"],
                "oi_btc":latest_oi["oi_btc"],
                "elapsed_seconds":oc["elapsed_seconds"],
                "snapshot_only":True}
            result["context_tags"].append("two_snapshot_oi_change_observed")
        else:result["warnings"].append("oi_change_missing_or_misaligned")
    available=sum(v is not None for v in result["observations"].values())
    if available>=4:result["status"]="multi_source_observational_context"
    # No long or short probabilities or entry recommendations from these
    # non-execution, non-continuous measurements.
    return result

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError,UnicodeError):return {}
    report=evaluate(read("BTC-okx-derivatives-context-v1.json"),
        read("BTC-okx-liquidity-history-analysis-v1.json"),
        read("BTC-okx-wall-persistence-v1.json"),
        read("BTC-okx-flow-coverage-v1.json"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX LIQUIDITY INTELLIGENCE:",report["status"],
          "available",sum(v is not None for v in report["observations"].values()),
          "decision",report["decision"],"warnings",report["warnings"])

if __name__=="__main__":main()
