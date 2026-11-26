#!/usr/bin/env python3
"""Isolated BingX perpetual BTC-USDT read-only candle probe.

BingX is the chart venue currently used by TradingView alerts. This is NOT
Binance futures, and the two sources must never be silently interchanged.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"data"/"BTC-bingx-futures-probe.json"
DURATIONS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800}
API="https://open-api.bingx.com/openApi/swap/v3/quote/klines"

def parse_response(payload,interval,now_ms):
    if interval not in DURATIONS:raise ValueError("invalid timeframe")
    if not isinstance(payload,dict) or payload.get("code")!=0 or not isinstance(payload.get("data"),list):
        raise ValueError("unverified BingX response")
    duration=DURATIONS[interval]
    candles=[]
    for item in payload["data"]:
        if not isinstance(item,dict):raise ValueError("invalid candle")
        stamp=int(item["time"])
        vals=[float(item[k]) for k in ("open","high","low","close")]
        if not all(math.isfinite(v) and v>0 for v in vals):
            raise ValueError("nonfinite price")
        o,h,l,c=vals
        if h<max(o,c) or l>min(o,c) or l>h:
            raise ValueError("invalid OHLC")
        if stamp+duration*1000>now_ms:continue
        if (stamp//1000//86400+3)%7!=0 if interval=="1w" else stamp%(duration*1000)!=0:
            raise ValueError("invalid open time alignment")
        candles.append({"t":stamp//1000,"o":o,"h":h,"l":l,"c":c})
    candles.sort(key=lambda x:x["t"])
    if len(candles)<30:raise ValueError("insufficient candles")
    if any(candles[i]["t"]-candles[i-1]["t"]!=duration for i in range(1,len(candles))):
        raise ValueError("gaps or duplicates")
    if now_ms//1000-(candles[-1]["t"]+duration)>duration+60:
        raise ValueError("stale candles")
    return candles

def fetch(interval):
    time.sleep(1.1)  # BingX documents 1 request / second / IP
    url=API+"?"+urlencode({"symbol":"BTC-USDT","interval":interval,"limit":300})
    with urlopen(Request(url,headers={"User-Agent":"BTC-Intelligence/1.0"}),timeout=20) as resp:
        return json.load(resp)

def collect(now=None,getter=fetch):
    now=now or dt.datetime.now(dt.timezone.utc)
    out={"schema_version":"1.0","source":"BingX USD-M Perpetual BTC-USDT",
         "venue":"BingX","symbol":"BTC-USDT","collected_at_utc":now.isoformat(),
         "status":"partial","timeframes":{},"errors":{},"trade_signal":None}
    for tf in DURATIONS:
        try:
            bars=parse_response(getter(tf),tf,int(now.timestamp()*1000))
            out["timeframes"][tf]={"status":"ok","bars":bars}
        except (OSError,ValueError,TypeError,KeyError,TimeoutError) as err:
            out["timeframes"][tf]={"status":"unavailable","bars":[]}
            out["errors"][tf]=type(err).__name__
    if all(r["status"]=="ok" for r in out["timeframes"].values()):
        out["status"]="verified"
    return out

def main():
    result=collect()
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,separators=(",",":"))+"\n",encoding="utf-8")
    print("BingX futures candles:",result["status"],"available",
          [k for k,v in result["timeframes"].items() if v["status"]=="ok"],
          "errors",result["errors"])
if __name__=="__main__":
    main()
