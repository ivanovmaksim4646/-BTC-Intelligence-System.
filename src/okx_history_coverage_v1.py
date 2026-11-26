#!/usr/bin/env python3
"""OKX REST historical trades: bounded pagination and honest M5 coverage.

Never claim a complete CVD window from a capped recent page. Use only
public OKX BTC-USDT-SWAP history-trades; verify original venue/contract.
This is a conservative API coverage DIAGNOSTIC, not a production trade signal.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"BTC-okx-history-coverage-v1.json"
INST="BTC-USDT-SWAP"
BASE="https://www.okx.com/api/v5/market/history-trades"
MAX_PAGES=30
PAGE_LIMIT=100

def fetch_page(cursor=None,opener=urlopen):
    args={"instId":INST,"type":"1","limit":str(PAGE_LIMIT)}
    if cursor is not None: args["after"]=str(cursor)  # older tradeId
    with opener(Request(BASE+"?"+urlencode(args),headers={
        "Accept":"application/json","User-Agent":"BTC-Intelligence-Coverage/1.0"}),timeout=20) as resp:
        data=json.load(resp)
    if not isinstance(data,dict) or str(data.get("code"))!="0" or not isinstance(data.get("data"),list):
        raise ValueError("unverified history response")
    return data["data"]

def verify_page(rows,prev_cursor,now_ms):
    if not isinstance(rows,list) or len(rows)>PAGE_LIMIT:
        raise ValueError("bad response size")
    parsed=[]
    previous_id=None
    for t in rows:
        if not isinstance(t,dict) or t.get("instId")!=INST or t.get("side") not in ("buy","sell"):
            raise ValueError("wrong instrument or side")
        try:
            ident=int(t["tradeId"]);ts=int(t["ts"]);size=float(t["sz"])
        except (ValueError,TypeError,KeyError) as exc:
            raise ValueError("invalid trade fields") from exc
        if (ident<=0 or not math.isfinite(size) or size<=0 or
            not 0<=now_ms-ts<=48*3600*1000):
            raise ValueError("invalid id, size or time")
        if (previous_id is not None and ident>=previous_id) or (
            prev_cursor is not None and ident>=prev_cursor):
            raise ValueError("trade ID pagination is not strictly descending")
        previous_id=ident
        parsed.append({"id":ident,"ts":ts,"side":t["side"],"size":size})
    if any(parsed[i]["ts"]>parsed[i-1]["ts"] for i in range(1,len(parsed))):
        raise ValueError("time ordering not descending")
    return parsed

def collect(getter=fetch_page,clock=None,max_pages=MAX_PAGES,contract_btc=None):
    clock=clock or dt.datetime.now(dt.timezone.utc)
    if clock.utcoffset() is None:
        raise ValueError("timezone-aware clock required")
    if type(max_pages)!=int or not 1<=max_pages<=30:
        raise ValueError("invalid page cap")
    if type(contract_btc) not in (int,float) or not math.isfinite(contract_btc) or contract_btc<=0:
        raise ValueError("unverified contract specification")
    # Most recently CLOSED UTC 5m interval; do not include active candle.
    now_ms=int(clock.timestamp()*1000)
    window_end_ms=now_ms//300000*300000
    window_start_ms=window_end_ms-300000
    out={"schema_version":"1.0","source":"OKX BTC-USDT-SWAP",
         "classification":"bounded_history_diagnostic_only",
         "collected_at_utc":clock.isoformat(),"window_start_ms":window_start_ms,
         "window_end_ms":window_end_ms,"status":"unverified",
         "coverage":"unknown","m5_delta_btc":None,"m5_cvd":None,
         "page_count":0,"trades_in_window":0,"oldest_ts_ms":None,
         "newest_ts_ms":None,"error":None,"entry_signal":False,"trade_signal":None}
    cursor=None;total=0.0;trades=0;earliest=None;latest=None;complete=False
    try:
        for i in range(max_pages):
            page=verify_page(getter(cursor),cursor,now_ms)
            if not page:
                break
            out["page_count"]+=1
            ids=[r["id"] for r in page]
            new_cursor=ids[-1]
            if cursor is not None and new_cursor>=cursor:
                raise ValueError("cursor stalled")
            cursor=new_cursor
            for row in page:
                if earliest is None or row["ts"]<earliest:earliest=row["ts"]
                if latest is None or row["ts"]>latest:latest=row["ts"]
                if window_start_ms<=row["ts"]<window_end_ms:
                    total+=(1 if row["side"]=="buy" else -1)*row["size"]*contract_btc
                    trades+=1
            if page[-1]["ts"]<window_start_ms:
                complete=True
                break
        out["trades_in_window"]=trades
        out["oldest_ts_ms"]=earliest;out["newest_ts_ms"]=latest
        if complete and latest is not None and latest>=window_end_ms and trades>0:
            # This proves bounded pagination crossed the window boundaries,
            # not exchange-wide completeness or clock-exact trade reporting.
            out["status"]="bounded_window_observed"
            out["coverage"]="pagination_crossed_both_m5_window_boundaries"
            out["m5_delta_btc"]=round(total,8)
            out["m5_cvd"]=None  # CVD needs persistent independently verified baseline
        else:
            out["status"]="insufficient_coverage"
            out["coverage"]="capped_or_missing_window_boundaries"
    except (OSError,ValueError,TypeError,KeyError,TimeoutError) as exc:
        out["status"]="unverified"
        out["coverage"]="api_or_integrity_failure"
        out["error"]=type(exc).__name__
        out["m5_delta_btc"]=None
    return out

def main():
    try:
        from src.okx_futures_orderflow_v1 import get_json
    except ModuleNotFoundError:
        from okx_futures_orderflow_v1 import get_json
    try:
        spec=get_json("/api/v5/public/instruments",{"instType":"SWAP","instId":INST})
        verified=[float(x["ctVal"]) for x in spec if x.get("instId")==INST and x.get("ctValCcy")=="BTC"]
        if len(verified)!=1:
            raise ValueError("contract metadata missing")
        result=collect(contract_btc=verified[0])
    except (OSError,ValueError,TypeError,KeyError,TimeoutError) as exc:
        result={"schema_version":"1.0","source":"OKX BTC-USDT-SWAP",
                "status":"unverified","coverage":"contract_metadata_unavailable",
                "error":type(exc).__name__,"trade_signal":None,"m5_delta_btc":None,
                "m5_cvd":None,"page_count":0,"trades_in_window":0}

    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX history:",result["status"],"pages",result["page_count"],
          "coverage",result["coverage"],"trades",result["trades_in_window"])

if __name__=="__main__":
    main()
