#!/usr/bin/env python3
"""Fail-closed, timestamped OKX resting-liquidity/funding/premium history.

Uses already-collected OKX *snapshots*, not exchange trade/order events.
Does not interpret changing resting walls as executed orders, liquidation,
complete delta/CVD, or reliable stop/target levels. No trading actions.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/"data"
HISTORY=DATA/"BTC-okx-liquidity-history-v1.jsonl"
REPORT=DATA/"BTC-okx-liquidity-history-analysis-v1.json"
SOURCE="OKX BTC-USDT-SWAP"
MAX_HISTORY=2500
MAX_REPORT_AGE=15*60
MAX_COMPARE_GAP=20*60
MAX_TIME_SKEW=180
EPS=1e-8

def finite(value):
    return type(value) in (float,int) and math.isfinite(value)

def valid_positive(value):
    return finite(value) and value>0

def age_seconds(iso,now):
    try:
        stamp=dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
        if stamp.tzinfo is None:return None
        return (now-stamp).total_seconds()
    except (ValueError,TypeError,AttributeError):return None

def valid_wall(x):
    return (isinstance(x,dict) and valid_positive(x.get("price"))
        and valid_positive(x.get("btc")) and valid_positive(x.get("contracts"))
        and valid_positive(x.get("notional_usdt")))

def create_observation(snapshot,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone_required")
    if not isinstance(snapshot,dict) or snapshot.get("source")!=SOURCE or (
        snapshot.get("classification")!="public_rest_snapshot_research_only"
    ):
        raise ValueError("unverified_source")
    age=age_seconds(snapshot.get("generated_at_utc"),now)
    if age is None or not 0<=age<=MAX_REPORT_AGE:
        raise ValueError("stale_snapshot")
    b=snapshot.get("book")
    if not isinstance(b,dict) or b.get("status")!="snapshot_only":
        raise ValueError("missing_verified_book")
    ts=b.get("timestamp_ms")
    if type(ts) is not int or ts<=0 or not 0<=now.timestamp()*1000-ts<=MAX_TIME_SKEW*1000:
        raise ValueError("stale_or_invalid_book_timestamp")
    bid=b.get("bid_depth_btc");ask=b.get("ask_depth_btc")
    if not valid_positive(bid) or not valid_positive(ask):
        raise ValueError("invalid_book_depth")
    best_bid=b.get("best_bid");best_ask=b.get("best_ask")
    if not valid_positive(best_bid) or not valid_positive(best_ask) or best_bid>=best_ask:
        raise ValueError("invalid_best_bid_ask")
    walls={}
    for side in ("bid","ask"):
        items=b.get(f"{side}_walls")
        if not isinstance(items,list) or len(items)>3 or not all(valid_wall(x) for x in items):
            raise ValueError("invalid_walls")
        if any((w["price"]>best_bid if side=="bid" else w["price"]<best_ask) for w in items):
            raise ValueError("walls_outside_book")
        walls[side]=[{"price":w["price"],"btc":w["btc"],
            "notional_usdt":w["notional_usdt"]} for w in items]
    obs={"source":SOURCE,"book_timestamp_ms":ts,
        "bid_depth_btc":round(bid,8),"ask_depth_btc":round(ask,8),
        "best_bid":best_bid,"best_ask":best_ask,
        "spread_bps":round(10000*(best_ask-best_bid)/((best_ask+best_bid)/2),5),
        "imbalance":round((bid-ask)/(bid+ask),6),
        "bid_walls":walls["bid"],"ask_walls":walls["ask"],
        "funding_rate_fraction":None,"funding_next_ms":None,
        "premium_bps":None,"mark_timestamp_ms":None,"index_timestamp_ms":None,
        "coverage":"single_cancelable_resting_book_snapshot",
        "trade_signal":None}
    f=snapshot.get("funding")
    if isinstance(f,dict) and f.get("status")=="quoted_rate_snapshot":
        rate=f.get("rate_fraction");next_ms=f.get("next_funding_time_ms")
        if (finite(rate) and abs(rate)<=.05 and type(next_ms) is int
            and 0<next_ms-now.timestamp()*1000<=48*3600*1000):
            obs["funding_rate_fraction"]=rate
            obs["funding_next_ms"]=next_ms
    m=snapshot.get("mark_index")
    if isinstance(m,dict) and m.get("status")=="two_recent_public_snapshots":
        mt=m.get("mark_timestamp_ms");it=m.get("index_timestamp_ms")
        mp=m.get("mark_price");ip=m.get("index_price")
        if (type(mt) is int and type(it) is int and abs(mt-it)<=120000
            and 0<=now.timestamp()*1000-mt<=MAX_TIME_SKEW*1000
            and 0<=now.timestamp()*1000-it<=MAX_TIME_SKEW*1000
            and valid_positive(mp) and valid_positive(ip)):
            obs["premium_bps"]=round(10000*(mp-ip)/ip,6)
            obs["mark_timestamp_ms"]=mt;obs["index_timestamp_ms"]=it
    return obs

def check_history_row(row):
    if not isinstance(row,dict) or row.get("source")!=SOURCE or row.get("trade_signal") is not None:
        return False
    if row.get("coverage")!="single_cancelable_resting_book_snapshot":
        return False
    if type(row.get("book_timestamp_ms")) is not int or row["book_timestamp_ms"]<=0:
        return False
    if not all(valid_positive(row.get(k)) for k in ("bid_depth_btc","ask_depth_btc","best_bid","best_ask")):
        return False
    if row["best_bid"]>=row["best_ask"]:return False
    if not finite(row.get("imbalance")) or not -1<=row["imbalance"]<=1:return False
    for side in ("bid","ask"):
        walls=row.get(side+"_walls")
        if not isinstance(walls,list) or len(walls)>3 or not all(isinstance(w,dict) and
              valid_positive(w.get("price")) and valid_positive(w.get("btc")) for w in walls):
            return False
    return True

def normalize(rows):
    if not isinstance(rows,list):raise ValueError("invalid_history")
    by_ts={}
    for x in rows:
        if not check_history_row(x):
            raise ValueError("corrupt_liquidity_history")
        t=x["book_timestamp_ms"]
        if t in by_ts and by_ts[t]!=x:
            raise ValueError("conflicting_history_timestamp")
        by_ts[t]=x
    return [by_ts[t] for t in sorted(by_ts)]

def compare(previous,current):
    if current["book_timestamp_ms"]<=previous["book_timestamp_ms"]:
        raise ValueError("non_chronological_snapshots")
    elapsed=(current["book_timestamp_ms"]-previous["book_timestamp_ms"])/1000
    if elapsed>MAX_COMPARE_GAP:
        return {"status":"unavailable","reason":"snapshot_gap_over_20m","elapsed_seconds":elapsed,
             "interval_fully_observed":False}
    bid_delta=current["bid_depth_btc"]-previous["bid_depth_btc"]
    ask_delta=current["ask_depth_btc"]-previous["ask_depth_btc"]
    out={"status":"two_sample_change_only","elapsed_seconds":elapsed,
        "interval_fully_observed":False,
        "bid_depth_change_btc":round(bid_delta,8),
        "ask_depth_change_btc":round(ask_delta,8),
        "imbalance_change":round(current["imbalance"]-previous["imbalance"],6),
        "best_bid_change_usdt":round(current["best_bid"]-previous["best_bid"],4),
        "best_ask_change_usdt":round(current["best_ask"]-previous["best_ask"],4),
        "funding_rate_change_fraction":None,
        "premium_change_bps":None,
        "interpretation":"resting_depth_snapshots_only_not_executed_volume"}
    if finite(previous.get("funding_rate_fraction")) and finite(current.get("funding_rate_fraction")):
        out["funding_rate_change_fraction"]=round(
            current["funding_rate_fraction"]-previous["funding_rate_fraction"],9)
    if finite(previous.get("premium_bps")) and finite(current.get("premium_bps")):
        out["premium_change_bps"]=round(current["premium_bps"]-previous["premium_bps"],6)
    return out

def analyze(snapshot,history,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    report={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":SOURCE,"classification":"historical_resting_liquidity_sampling_only",
       "new_record":False,"saved_count":0,"latest":None,"change":None,
       "warnings":[],"complete_m5_delta_btc":None,"complete_cvd_btc":None,
       "liquidation_heatmap":None,"trade_signal":None}
    try:
        existing=normalize(history)
    except ValueError as exc:
        report["warnings"].append(str(exc))
        return report,None
    try:record=create_observation(snapshot,now)
    except ValueError as exc:
        report["warnings"].append(str(exc))
        report["saved_count"]=len(existing)
        return report,existing
    last=existing[-1] if existing else None
    if last:
        if record["book_timestamp_ms"]<last["book_timestamp_ms"]:
            report["warnings"].append("out_of_order_snapshot_no_append")
        elif record["book_timestamp_ms"]==last["book_timestamp_ms"]:
            if last!=record:report["warnings"].append("same_timestamp_conflicting_snapshot")
            else:report["warnings"].append("duplicate_timestamp_no_append")
        else:
            report["change"]=compare(last,record)
            existing.append(record);report["new_record"]=True
    else:
        existing.append(record);report["new_record"]=True
    existing=existing[-MAX_HISTORY:]
    report["saved_count"]=len(existing)
    report["latest"]=existing[-1] if existing else None
    return report,existing

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    old=[];corrupted=False
    if HISTORY.exists():
        for line in HISTORY.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            try:old.append(json.loads(line))
            except (ValueError,TypeError):corrupted=True
    report,updated=analyze(read("BTC-okx-liquidity-derivatives-v1.json"),old)
    if corrupted:
        report["warnings"].append("invalid_json_line_in_history")
        updated=None
    if updated is not None and report["new_record"] and not corrupted:
        HISTORY.parent.mkdir(parents=True,exist_ok=True)
        tmp=HISTORY.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n"
            for x in updated),encoding="utf-8")
        tmp.replace(HISTORY)
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    tmp=REPORT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(REPORT)
    print("OKX resting liquidity:",report["saved_count"],"samples",
          "new",report["new_record"],"change",(report["change"] or {}).get("status"),
          "warnings",report["warnings"])

if __name__=="__main__":main()
