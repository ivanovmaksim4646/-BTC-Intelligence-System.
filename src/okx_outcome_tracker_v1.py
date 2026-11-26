#!/usr/bin/env python3
"""OKX M5 paper-entry outcome tracker, strictly research-only.

Consumes a future, independently validated paper-entry journal, never raw
TradingView observations. Replays ONLY continuous, closed OKX M5 candles after
an entry close; persists each bar into a bounded append-only OHLC archive to
survive the OKX 299-bar REST lookback. No order placement or synthetic trade
generation. Ambiguous intrabar fills and data gaps are censored.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
try:
    from src.rr_outcome_research_v1 import compare_rr_paths
    from src.rr_statistics_v1 import build as build_statistics
except ModuleNotFoundError:
    from rr_outcome_research_v1 import compare_rr_paths
    from rr_statistics_v1 import build as build_statistics

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
VENUE="OKX BTC-USDT-SWAP"
M5=300
MAX_ARCHIVE_BARS=10000  # ~34 days; do not silently certify older outcomes.
MAX_JOURNAL_ENTRIES=3000
CANDLES=DATA/"BTC-okx-futures-candles.json"
ENTRIES=DATA/"BTC-okx-validated-paper-entries-v1.jsonl"
ARCHIVE=DATA/"BTC-okx-m5-closed-history-v1.jsonl"
RESULTS=DATA/"BTC-rr-validated-outcomes-v1.jsonl"
AUDIT=DATA/"BTC-okx-outcome-tracker-v1.json"
STATS=DATA/"BTC-rr-statistics-v1.json"

def finite(v):
    return type(v) in (float,int) and math.isfinite(v) and v>0

def canonical(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def check_bar(b):
    if not isinstance(b,dict) or set(b)!={"t","o","h","l","c"}:
        return False
    if type(b["t"]) is not int or b["t"]<0 or b["t"]%M5:
        return False
    if not all(finite(b[k]) for k in ("o","h","l","c")):
        return False
    return b["l"]<=min(b["o"],b["c"])<=max(b["o"],b["c"])<=b["h"]

def read_jsonl(path):
    if not path.exists():return [],0
    rows=[];bad=0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:
            v=json.loads(line)
            if not isinstance(v,dict):raise ValueError("not object")
            rows.append(v)
        except (ValueError,TypeError):
            bad+=1
    return rows,bad

def good_snapshot(snap,now):
    if not isinstance(snap,dict) or snap.get("source")!=VENUE or snap.get("status")!="verified":
        return False
    try:
        timestamp=dt.datetime.fromisoformat(snap["collected_at_utc"].replace("Z","+00:00"))
        if timestamp.tzinfo is None or not dt.timedelta(0)<=now-timestamp<=dt.timedelta(minutes=15):
            return False
        frame=snap["timeframes"]["5m"]
        bars=frame["bars"]
        return frame.get("status")=="ok" and len(bars)>=30 and all(check_bar(x) for x in bars) and all(
            bars[i]["t"]-bars[i-1]["t"]==M5 for i in range(1,len(bars)))
    except (KeyError,ValueError,TypeError,AttributeError):
        return False

def merge_archive(existing,new_bars):
    """Deduplicate by candle OPEN timestamp; any OHLC revision blocks unsafe merge."""
    merged={}
    for b in existing:
        if not check_bar(b):raise ValueError("invalid_archived_candle")
        t=b["t"]
        if t in merged and canonical(merged[t])!=canonical(b):
            raise ValueError("conflicting_archive_duplicate")
        merged[t]=b
    for b in new_bars:
        if not check_bar(b):raise ValueError("invalid_new_candle")
        t=b["t"]
        if t in merged and canonical(merged[t])!=canonical(b):
            raise ValueError("okx_historical_candle_revised")
        merged[t]=b
    result=[merged[t] for t in sorted(merged)]
    # Keep full archive while windows can be tracked. If retention is reached,
    # trim history and explicitly mark entries outside retained history as censored.
    return result[-MAX_ARCHIVE_BARS:]

def check_entry(row):
    """Narrow entry contract. This is a paper hypothesis, never an executed trade.

    Independent confirmation must be provided by a future deterministic entry
    validator; caller-provided bool flags alone cannot certify provenance.
    """
    if not isinstance(row,dict):return False
    if (row.get("source")!=VENUE or row.get("classification")!="validated_paper_entry_only"
        or row.get("execution")!="not_executed" or row.get("entry_signal") is not False
        or row.get("trade_signal") is not None
        or row.get("independent_entry_validator")!="okx_poi_qm_execution_validator_v1"):
        return False
    ident=row.get("entry_id")
    if not isinstance(ident,str) or not (8<=len(ident)<=128):return False
    if row.get("direction") not in ("long","short"):return False
    entry=row.get("entry");stop=row.get("stop_loss");target=row.get("take_profit")
    if not all(finite(x) for x in (entry,stop,target)):return False
    if not ((stop<entry<target) if row["direction"]=="long" else (target<entry<stop)):
        return False
    close=row.get("entry_close_utc")
    if type(close) is not int or close<=0 or close%M5:return False
    if row.get("venue_candle_close_verified") is not True or row.get("independent_target_verified") is not True:
        return False
    if row.get("risk_fraction")!=0.01 and (
        type(row.get("risk_fraction")) not in (int,float) or not 0<row["risk_fraction"]<=0.01):
        return False
    if (type(row.get("leverage_cap")) not in (int,float) or
        not 0<row["leverage_cap"]<=5):return False
    if (type(row.get("total_cost_bps")) not in (int,float) or
        not math.isfinite(row["total_cost_bps"]) or row["total_cost_bps"]<0):
        return False
    return True

def evaluate(entries,archived,now=None):
    """Outcome replay; only contiguous future OKX data, no lookahead/gap repair."""
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone-aware now required")
    if not isinstance(entries,list) or not isinstance(archived,list):
        raise ValueError("entries and bars required")
    if not all(check_bar(b) for b in archived):
        raise ValueError("invalid OHLC archive")
    if any(archived[i]["t"]<=archived[i-1]["t"] for i in range(1,len(archived))):
        raise ValueError("unordered OHLC archive")
    outcomes=[];pending=[];rejected=[];seen=set()
    for entry in entries[:MAX_JOURNAL_ENTRIES]:
        ident=entry.get("entry_id") if isinstance(entry,dict) else None
        if not check_entry(entry) or ident in seen:
            rejected.append({"entry_id":ident,"reason":"invalid_or_duplicate_entry_provenance"})
            continue
        seen.add(ident)
        close=entry["entry_close_utc"]
        if close>now.timestamp():
            pending.append({"entry_id":ident,"reason":"entry_from_future"})
            continue
        if not archived or archived[0]["t"]>close:
            pending.append({"entry_id":ident,"reason":"entry_outside_retained_history"})
            continue
        future=[b for b in archived if b["t"]>=close and b["t"]+M5<=now.timestamp()]
        if not future:
            pending.append({"entry_id":ident,"reason":"awaiting_next_closed_m5"})
            continue
        if future[0]["t"]!=close or any(future[i]["t"]-future[i-1]["t"]!=M5 for i in range(1,len(future))):
            pending.append({"entry_id":ident,"reason":"missing_m5_data_no_interpolation"})
            continue
        # The existing first-touch evaluator expects strictly later timestamps
        # and a closed=True flag; convert OKX candle OPEN to CLOSE timestamps.
        closed=[{**b,"t":b["t"]+M5,"closed":True} for b in future]
        simulated=compare_rr_paths(entry["direction"],entry["entry"],entry["stop_loss"],
                  close,closed,total_cost_bps=entry["total_cost_bps"])
        states=simulated["outcomes"]
        # For durable per-R results only emit complete entries: all thresholds
        # resolved (win/loss/ambiguous/invalid), never pretend unresolved=loss.
        terminal={"target_first","stop_first","ambiguous_same_candle","invalid_target_geometry"}
        if not all(x["status"] in terminal for x in states.values()):
            pending.append({"entry_id":ident,"reason":"open_rr_thresholds",
                            "unresolved":sum(x["status"]=="unresolved" for x in states.values())})
            continue
        # A same-bar ambiguity remains censored; summary aggregator excludes it.
        outcomes.append({"entry_id":ident,"source":VENUE,
            "classification":"validated_closed_candle_counterfactual",
            "entry_provenance_verified":True,"future_bars_verified":True,
            "direction":entry["direction"],"entry_close_utc":close,
            "model":entry.get("model"),"trading_session":entry.get("trading_session"),
            "cost_assumption_bps":entry["total_cost_bps"],"outcomes":states,
            "observation_last_closed_utc":closed[-1]["t"],
            "trade_signal":None})
    return {"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "classification":"okx_paper_outcome_tracking_only","source":VENUE,
       "candidates":len(entries),"resolved_entries":len(outcomes),
       "pending_entries":len(pending),"rejected_entries":len(rejected),
       "pending":pending[:30],"rejected":rejected[:30],
       "results":outcomes,"trade_signal":None,"execution_enabled":False}

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    now=dt.datetime.now(dt.timezone.utc)
    snap=read(CANDLES.name)
    existing,bad_bars=read_jsonl(ARCHIVE)
    rows,bad_entries=read_jsonl(ENTRIES)
    old_results,bad_results=read_jsonl(RESULTS)
    DATA.mkdir(parents=True,exist_ok=True)
    warning=[]
    if not good_snapshot(snap,now):
        warning.append("okx_closed_candle_snapshot_missing_or_stale")
        bars=existing
    else:
        try:bars=merge_archive(existing,snap["timeframes"]["5m"]["bars"])
        except ValueError as exc:
            bars=existing
            warning.append(str(exc))
    if bad_bars:
        warning.append("malformed_candle_archive")
        bars=existing
    if bad_entries:warning.append("malformed_paper_entry_journal")
    if bad_results:warning.append("malformed_existing_outcomes")
    # Never use corrupt or previously known conflicting data for outcomes.
    safe=(not warning and good_snapshot(snap,now))
    if safe:
        ARCHIVE.write_text("".join(canonical(x)+"\n" for x in bars),encoding="utf-8")
    report=evaluate(rows,bars,now) if safe else {
        "schema_version":"1.0","generated_at_utc":now.isoformat(),
        "source":VENUE,"classification":"okx_paper_outcome_tracking_only",
        "candidates":len(rows),"resolved_entries":0,"pending_entries":len(rows),
        "rejected_entries":0,"pending":[],"rejected":[],"results":[],
        "trade_signal":None,"execution_enabled":False}
    report["warnings"]=warning
    previous={x.get("entry_id"):x for x in old_results if isinstance(x,dict)}
    newly=[]
    if safe:
        for record in report["results"]:
            eid=record["entry_id"]
            if eid not in previous:
                newly.append(record)
            elif previous[eid].get("outcomes")!=record["outcomes"]:
                report["warnings"].append("existing_outcome_conflict_no_overwrite")
    if newly and not report["warnings"]:
        with RESULTS.open("a",encoding="utf-8") as file:
            for record in newly:file.write(canonical(record)+"\n")
    report["newly_finalized"]=len(newly) if not report["warnings"] else 0
    report.pop("results",None)
    t=AUDIT.with_suffix(".json.tmp")
    t.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(AUDIT)
    # This report is rebuilt AFTER the outcomes are finalized in the same run.
    if not report["warnings"]:
        all_results,_=read_jsonl(RESULTS)
        stats=build_statistics(all_results,now)
        t=STATS.with_suffix(".json.tmp")
        t.write_text(json.dumps(stats,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        t.replace(STATS)
    print("OKX outcome tracker:",report["newly_finalized"],"new entries",
          report["pending_entries"],"pending; warnings:",report["warnings"])

if __name__=="__main__":main()
