#!/usr/bin/env python3
"""OKX REST order-flow coverage audit + real OI snapshot history (research only).

A 500-trade REST page is NOT a complete M5 stream. The original signed
page delta remains an observation; NEVER promote it to complete M5/H4 CVD.
OI *change* can be calculated from two authentic fresh successive OKX OI
snapshots, with explicit timestamps and age limits. No live trading.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-flow-coverage-v1.json"
OI_HISTORY=DATA/"BTC-okx-oi-observations-v1.jsonl"
VENUE="OKX BTC-USDT-SWAP"
WINDOWS={"5m":300,"15m":900,"1h":3600,"4h":14400}
MAX_OI_RECORDS=2500
MAX_OI_INTERVAL_SECONDS=20*60

def number(x):
    return type(x) in (float,int) and math.isfinite(x) and x>0

def check_oi(snap):
    return (isinstance(snap,dict)
        and snap.get("source")==VENUE and
        isinstance(snap.get("open_interest"),dict) and
        snap["open_interest"].get("status")=="snapshot_only"
        and number(snap["open_interest"].get("value_btc_reported"))
        and type(snap["open_interest"].get("timestamp_ms")) is int
        and snap["open_interest"]["timestamp_ms"]>0)

def normalize_history(rows):
    if not isinstance(rows,list):raise ValueError("invalid_history")
    unique={}
    for row in rows:
        if (not isinstance(row,dict) or
            type(row.get("timestamp_ms")) is not int or row["timestamp_ms"]<=0 or
            not number(row.get("oi_btc")) or row.get("source")!=VENUE):
            raise ValueError("corrupt_oi_history")
        t=row["timestamp_ms"]
        if t in unique and unique[t]["oi_btc"]!=row["oi_btc"]:
            raise ValueError("conflicting_oi_snapshot")
        unique[t]=row
    return [unique[t] for t in sorted(unique)]

def evaluate(snap,old_history,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone_required")
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":VENUE,"classification":"partial_rest_flow_audit_only",
       "status":"unavailable","trade_signal":None,"entry_signal":False,
       "sampled_rest_page":None,"complete_m5_delta_btc":None,
       "complete_cvd_btc":None,"continuous_cvd_5m_15m_1h_4h":False,
       "oi_change":None,"oi_snapshot":None,
       "coverage_by_window":{tf:{"seconds":seconds,"full_coverage_verified":False,
                                 "delta_btc":None,"cvd_btc":None}
                             for tf,seconds in WINDOWS.items()},
       "warnings":[]}
    try:hist=normalize_history(old_history)
    except ValueError as exc:
        result["warnings"].append(str(exc));return result,[]
    if not isinstance(snap,dict) or snap.get("source")!=VENUE:
        result["warnings"].append("missing_or_wrong_venue");return result,hist
    try:
        collected=dt.datetime.fromisoformat(snap["collected_at_utc"].replace("Z","+00:00"))
    except (KeyError,AttributeError,TypeError,ValueError):
        collected=None
    if collected is None or collected.utcoffset() is None or not 0<=(now-collected).total_seconds()<=900:
        result["warnings"].append("stale_orderflow_snapshot");return result,hist
    trade=snap.get("recent_trades")
    if (isinstance(trade,dict) and trade.get("status")=="observed"
        and trade.get("coverage")=="limited_page_not_full_window"
        and type(trade.get("count")) is int and 0<trade["count"]<=500
        and type(trade.get("earliest_ts_ms")) is int
        and type(trade.get("latest_ts_ms")) is int
        and trade["earliest_ts_ms"]<=trade["latest_ts_ms"]
        and number(trade.get("ctVal_btc_per_contract"))
        and type(trade.get("signed_btc_in_returned_page")) in (float,int)
        and math.isfinite(trade["signed_btc_in_returned_page"])):
        start,end=trade["earliest_ts_ms"],trade["latest_ts_ms"]
        if 0<=now.timestamp()*1000-end<=900000 and 0<=now.timestamp()*1000-start<=900000:
            result["sampled_rest_page"]={
                "count":trade["count"],"earliest_ts_ms":start,"latest_ts_ms":end,
                "sampled_duration_seconds":round((end-start)/1000,3),
                "signed_btc_in_page":trade["signed_btc_in_returned_page"],
                "coverage":"NOT_A_FULL_WINDOW"}
            for tf,seconds in WINDOWS.items():
                # Count a WHOLE window as definitely incomplete when its
                # observed page spans less than that timeframe, even when
                # successive GitHub Actions appear to run on schedule.
                result["coverage_by_window"][tf]["last_page_spans_full_window"]=(end-start)>=seconds*1000
                result["coverage_by_window"][tf]["page_trade_limit_reached"]=trade["count"]==500
        else:result["warnings"].append("stale_trade_page")
    else:result["warnings"].append("no_verified_trade_page")
    if check_oi(snap):
        row=snap["open_interest"]
        ts=row["timestamp_ms"]
        if 0<=now.timestamp()*1000-ts<=900000:
            value=row["value_btc_reported"]
            current={"source":VENUE,"timestamp_ms":ts,"oi_btc":value}
            if hist and hist[-1]["timestamp_ms"]==ts:
                if hist[-1]["oi_btc"]!=value:
                    result["warnings"].append("conflicting_oi_snapshot")
                else:
                    result["warnings"].append("duplicate_oi_snapshot")
            elif hist and ts<hist[-1]["timestamp_ms"]:
                result["warnings"].append("out_of_order_oi_snapshot")
            else:
                prev=hist[-1] if hist else None
                hist.append(current)
                hist=hist[-MAX_OI_RECORDS:]
                if prev:
                    elapsed=(ts-prev["timestamp_ms"])/1000
                    if 0<elapsed<=MAX_OI_INTERVAL_SECONDS:
                        diff=value-prev["oi_btc"]
                        result["oi_change"]={"status":"two_verified_snapshots",
                            "delta_btc":round(diff,8),
                            "delta_percent":round(100*diff/prev["oi_btc"],5),
                            "elapsed_seconds":elapsed,
                            "previous_timestamp_ms":prev["timestamp_ms"],
                            "current_timestamp_ms":ts,
                            "limitation":"not_continuous_intraperiod_OI"}
                    else:result["warnings"].append("oi_snapshot_gap_too_large")
            result["oi_snapshot"]={"oi_btc":value,"timestamp_ms":ts}
        else:result["warnings"].append("stale_oi_snapshot")
    else:result["warnings"].append("oi_snapshot_unavailable")
    result["status"]="sampled_only" if result["sampled_rest_page"] else "unavailable"
    result["observed_oi_snapshots"]=len(hist)
    return result,hist

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    old=[];bad=False
    if OI_HISTORY.exists():
        for line in OI_HISTORY.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            try:old.append(json.loads(line))
            except ValueError:bad=True
    report,updated=evaluate(read("BTC-okx-orderflow-v1.json"),old)
    if bad:
        report["warnings"].append("corrupt_oi_jsonl_no_write")
    else:
        OI_HISTORY.parent.mkdir(parents=True,exist_ok=True)
        if updated!=old:
            tmp=OI_HISTORY.with_suffix(".jsonl.tmp")
            tmp.write_text("".join(json.dumps(x,separators=(",",":"))+"\n" for x in updated),encoding="utf-8")
            tmp.replace(OI_HISTORY)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX Flow coverage:",report["status"],"OI change",report["oi_change"],
          "M5 complete",report["coverage_by_window"]["5m"]["full_coverage_verified"],
          "warnings",report["warnings"])

if __name__=="__main__":main()
