#!/usr/bin/env python3
"""Read-only, same-venue OKX BTC-USDT-SWAP CLOSED candle collector.

M5/M15/H1/H4/D1/W1 are all requested from OKX, never merged with
BingX, Binance or Kraken. Explicit UTC daily/weekly bars prevent
time-zone shifted candle boundaries. Fail closed on missing/gapped,
forming, stale or malformed market data. No order placement.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"BTC-okx-futures-candles.json"
SOURCE="OKX BTC-USDT-SWAP"
INSTRUMENT="BTC-USDT-SWAP"
API="https://www.okx.com/api/v5/market/candles"
INTERVALS={
    "5m":("5m",300),
    "15m":("15m",900),
    "1h":("1H",3600),
    "4h":("4H",14400),
    "1d":("1Dutc",86400),
    "1w":("1Wutc",604800),
}

def parse_candles(rows, tf, now_ms):
    if tf not in INTERVALS:raise ValueError("unsupported timeframe")
    seconds=INTERVALS[tf][1]
    if not isinstance(rows,list):raise ValueError("invalid OKX candle rows")
    observed={}
    previous_ms=None
    for row in rows:
        if not isinstance(row,list) or len(row)<9:
            raise ValueError("bad candle shape")
        if str(row[8]) not in ("0","1"):
            raise ValueError("invalid OKX confirm value")
        try:
            ts_ms=int(row[0]);o,h,l,c=(float(x) for x in row[1:5])
        except (ValueError,TypeError) as exc:raise ValueError("bad candle fields") from exc
        if ts_ms<0 or (not all(math.isfinite(v) and v>0 for v in (o,h,l,c))
             or l>min(o,c) or h<max(o,c) or l>h):
            raise ValueError("invalid OHLC")
        if ts_ms%1000:raise ValueError("unaligned milliseconds")
        ts=ts_ms//1000
        if tf=="1w":
            if (ts-345600)%seconds!=0:raise ValueError("week does not start Monday UTC")
        elif ts%seconds!=0:
            raise ValueError("bar starts at wrong UTC boundary")
        if previous_ms is not None and ts_ms>=previous_ms:
            raise ValueError("OKX candles not newest first")
        previous_ms=ts_ms
        if str(row[8])=="0":
            # Never treat forming candle as closed, regardless of timestamp.
            continue
        if ts_ms+seconds*1000>now_ms:
            raise ValueError("future-confirmed candle")
        if ts in observed:raise ValueError("duplicate candle")
        observed[ts]={"t":ts,"o":o,"h":h,"l":l,"c":c}
    bars=sorted(observed.values(),key=lambda x:x["t"])
    if len(bars)<30:
        raise ValueError("insufficient closed candles")
    if any(bars[i]["t"]-bars[i-1]["t"]!=seconds for i in range(1,len(bars))):
        raise ValueError("missing closed candle")
    # Newly closed bars can briefly lag exchange publication; beyond one
    # entire additional interval (+60s) is unusable as current structure.
    age_ms=now_ms-(bars[-1]["t"]+seconds)*1000
    if age_ms<0 or age_ms>(seconds+60)*1000:
        raise ValueError("stale closed candle")
    return bars

def fetch(tf,opener=urlopen):
    if tf not in INTERVALS:raise ValueError("unsupported timeframe")
    interval=INTERVALS[tf][0]
    url=API+"?"+urlencode({"instId":INSTRUMENT,"bar":interval,"limit":300})
    with opener(Request(url,headers={
        "User-Agent":"BTC-Intelligence-OKX-ICT/1.0","Accept":"application/json"}),timeout=20) as r:
        payload=json.load(r)
    if (not isinstance(payload,dict) or str(payload.get("code"))!="0"
        or not isinstance(payload.get("data"),list)):
        raise ValueError("unverified OKX response")
    return payload["data"]

def collect(now=None,getter=fetch,target_close_s=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone-aware now required")
    result={"schema_version":"1.0","source":SOURCE,"venue":"OKX",
            "instrument":INSTRUMENT,"collected_at_utc":now.isoformat(),
            "status":"partial","timeframes":{},"errors":{},
            "classification":"closed_futures_candles_research_only","trade_signal":None}
    if target_close_s is not None and (type(target_close_s) is not int or target_close_s%300 or not 0<=now.timestamp()-target_close_s<=420):
        raise ValueError("invalid or stale shared close")
    result["target_close_s"]=target_close_s
    for tf in INTERVALS:
        try:
            if target_close_s is None:
                bars=parse_candles(getter(tf),tf,int(now.timestamp()*1000))
            else:
                step=INTERVALS[tf][1]
                offset=345600 if tf=="1w" else 0
                expected=(target_close_s-offset)//step*step+offset
                raw=getter(tf)
                # Preserve validation of all rows eligible at the shared cutoff.
                selected=[r for r in raw if int(r[0])+step*1000<=expected*1000]
                bars=parse_candles(selected,tf,expected*1000)
                if bars[-1]["t"]+step!=expected:raise ValueError("shared close missing")
            result["timeframes"][tf]={"status":"ok","bars":bars}
        except (OSError,ValueError,TypeError,KeyError,OverflowError,TimeoutError) as exc:
            result["timeframes"][tf]={"status":"unavailable","bars":[]}
            result["errors"][tf]=type(exc).__name__
    if not result["errors"]:
        result["status"]="verified"
    return result

def main():
    out=collect(target_close_s=int(os.environ['BTC_SHARED_CLOSE_S']) if os.environ.get('BTC_SHARED_CLOSE_S') else None)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX futures M5-W1:",out["status"],"ok",
          [tf for tf,r in out["timeframes"].items() if r["status"]=="ok"],
          "errors",out["errors"])

if __name__=="__main__":main()
