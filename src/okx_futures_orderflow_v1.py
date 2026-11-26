#!/usr/bin/env python3
"""OKX BTC-USDT-SWAP independent public REST diagnostic, fail-closed.

Trades are a *limited recent page*, NOT complete M5 CVD. Size is contract
units until exact instrument ctVal and ctValCcy are verified. OI snapshots
are not OI change. This module makes no trading recommendation.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"BTC-okx-orderflow-v1.json"
BASE="https://www.okx.com"
SYMBOL="BTC-USDT-SWAP"

def get_json(path, params, opener=urlopen):
    url=BASE+path+"?"+urlencode(params)
    with opener(Request(url,headers={"User-Agent":"BTC-Intelligence-Research/1.0","Accept":"application/json"}),timeout=20) as response:
        data=json.load(response)
    if not isinstance(data,dict) or str(data.get("code"))!="0" or not isinstance(data.get("data"),list):
        raise ValueError("OKX API response not verified")
    return data["data"]

def pos(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError,TypeError,OverflowError):
        return None

def observe(trades, candles, oi, instrument, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    result={"schema_version":"1.0","source":"OKX BTC-USDT-SWAP",
            "collected_at_utc":now.isoformat(),"classification":"research_orderflow_only",
            "status":"partial","trade_signal":None,"entry_signal":False,
            "recent_trades":{"status":"unavailable","coverage":"limited_page_not_full_window"},
            "m5_cvd":None,"m5_delta_btc":None,"open_interest":None,
            "candles":{"status":"unavailable"},"notes":[]}
    rows = sorted(trades,key=lambda x:int(x.get("ts","0"))) if isinstance(trades,list) else []
    contract=None
    if isinstance(instrument,list):
        for item in instrument:
            if item.get("instId")==SYMBOL and item.get("ctValCcy")=="BTC":
                contract=pos(item.get("ctVal"))
    if rows and contract:
        ids=set(); signed=0; count=0; latest=0; earliest=None; valid=True
        for trade in rows:
            if not isinstance(trade,dict) or trade.get("instId")!=SYMBOL or trade.get("side") not in ("buy","sell"):
                valid=False;break
            trade_id=trade.get("tradeId")
            sz=pos(trade.get("sz"))
            try: t=int(trade.get("ts"))
            except (TypeError,ValueError):valid=False;break
            if not trade_id or trade_id in ids or sz is None or not 0<=now.timestamp()*1000-t<=900000:
                valid=False;break
            ids.add(trade_id);count+=1;latest=max(latest,t);earliest=t if earliest is None else min(earliest,t)
            signed+=(1 if trade["side"]=="buy" else -1)*sz*contract
        if valid:
            result["recent_trades"]={"status":"observed","count":count,
                "signed_btc_in_returned_page":round(signed,8),
                "earliest_ts_ms":earliest,"latest_ts_ms":latest,
                "coverage":"limited_page_not_full_window",
                "ctVal_btc_per_contract":contract}
    # OKX candle confirm=1 indicates closed; do not use forming candle.
    if isinstance(candles,list) and candles:
        parsed=[]
        for row in candles:
            if not isinstance(row,list) or len(row)<9 or str(row[8])!="1":continue
            try:
                ts=int(row[0]);o,h,l,c=map(float,row[1:5])
            except (ValueError,TypeError):continue
            if (all(math.isfinite(v) and v>0 for v in (o,h,l,c))
                and l<=min(o,c)<=max(o,c)<=h):
                parsed.append({"t":ts//1000,"o":o,"h":h,"l":l,"c":c})
        parsed.sort(key=lambda x:x["t"])
        if (len(parsed)>=20 and all(parsed[i]["t"]-parsed[i-1]["t"]==300 for i in range(1,len(parsed)))
            and 0<=now.timestamp()-(parsed[-1]["t"]+300)<=600):
            result["candles"]={"status":"observed","count":len(parsed),
                               "last_closed_open_utc":dt.datetime.fromtimestamp(parsed[-1]["t"],dt.timezone.utc).isoformat(),
                               "close":parsed[-1]["c"]}
    if isinstance(oi,list):
        for item in oi:
            if item.get("instId")!=SYMBOL:continue
            value=pos(item.get("oiCcy"))
            try: ts=int(item["ts"])
            except (KeyError,TypeError,ValueError):continue
            if value is not None and 0<=now.timestamp()*1000-ts<=900000:
                result["open_interest"]={"value_btc_reported":value,
                    "timestamp_ms":ts,"change":None,"status":"snapshot_only"}
    if (result["recent_trades"]["status"]=="observed"
        and result["candles"]["status"]=="observed" and result["open_interest"] is not None):
        result["status"]="observed_partial_coverage"
    result["notes"]=["Recent trades page is capped and cannot establish complete M5 CVD/Delta.",
                     "Trade contract size is verified from the OKX instrument metadata.",
                     "OI is a snapshot, not an OI change; no trade signal."]
    return result

def collect(now=None, getter=get_json):
    now=now or dt.datetime.now(dt.timezone.utc)
    reqs={
        "trades":("/api/v5/market/trades",{"instId":SYMBOL,"limit":500}),
        "candles":("/api/v5/market/candles",{"instId":SYMBOL,"bar":"5m","limit":60}),
        "oi":("/api/v5/public/open-interest",{"instType":"SWAP","instId":SYMBOL}),
        "instrument":("/api/v5/public/instruments",{"instType":"SWAP","instId":SYMBOL}),
    }
    datasets={};failures={}
    for name,(path,params) in reqs.items():
        try:datasets[name]=getter(path,params)
        except (OSError,ValueError,TypeError,KeyError,TimeoutError) as exc:
            datasets[name]=[]
            failures[name]=type(exc).__name__
    result=observe(datasets["trades"],datasets["candles"],datasets["oi"],datasets["instrument"],now)
    result["endpoint_errors"]=failures
    if failures:result["status"]="partial"
    return result

def main():
    output=collect()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX collector:",output["status"],"errors:",output["endpoint_errors"],
          "trades:",output["recent_trades"]["status"],"candles:",output["candles"]["status"])

if __name__=="__main__":
    main()
