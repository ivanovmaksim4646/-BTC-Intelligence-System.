#!/usr/bin/env python3
"""Independent, fail-closed Binance USD-M BTCUSDT PERPETUAL candle collector.

Only CLOSED, consecutive futures candles are eligible; never infer missing
candles from Kraken Spot or unverified TradingView events. Read-only API.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"BTC-binance-futures-candles.json"
BASE="https://fapi.binance.com/fapi/v1/klines"
INTERVALS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400,"1w":604800}
LIMIT=300

def parse_klines(rows, seconds, now_ms):
    if not isinstance(rows,list):
        raise ValueError("invalid response shape")
    bars=[]
    for r in rows:
        if not isinstance(r,list) or len(r)<7:
            raise ValueError("invalid kline")
        open_ms=int(r[0]); close_ms=int(r[6])
        if close_ms+1>now_ms: # exclude forming candle
            continue
        vals=list(map(float,r[1:5]))
        if (not all(math.isfinite(x) and x>0 for x in vals)
            or vals[1]<max(vals[0],vals[3])
            or vals[2]>min(vals[0],vals[3])
            or (open_ms % (seconds*1000)!=0 if seconds!=604800 else (open_ms//1000//86400+3)%7!=0)
            or close_ms-open_ms+1!=seconds*1000):
            raise ValueError("invalid OHLC or candle bounds")
        bars.append({"t":open_ms//1000,"o":vals[0],"h":vals[1],"l":vals[2],"c":vals[3]})
    bars=sorted(bars,key=lambda b:b["t"])
    if not bars or any(bars[i]["t"]-bars[i-1]["t"] != seconds for i in range(1,len(bars))):
        raise ValueError("missing or duplicate candle")
    if now_ms//1000-(bars[-1]["t"]+seconds)>seconds+60:
        raise ValueError("last candle is stale")
    return bars

def fetch(interval):
    from urllib.parse import urlencode
    url=BASE+"?"+urlencode({"symbol":"BTCUSDT","interval":interval,"limit":LIMIT})
    with urlopen(Request(url,headers={"User-Agent":"BTC-Intelligence/1.0"}),timeout=20) as resp:
        return json.load(resp)

def collect(now=None, getter=fetch):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None: raise ValueError("aware clock required")
    stamp=int(now.timestamp()*1000)
    out={"schema_version":"1.0","source":"Binance USD-M Futures BTCUSDT PERPETUAL",
         "market":"BTCUSDT","collected_at_utc":now.astimezone(dt.timezone.utc).isoformat(),
         "status":"partial","timeframes":{},"errors":{},"no_trade_on_partial":True}
    for interval,duration in INTERVALS.items():
        try:
            bars=parse_klines(getter(interval),duration,stamp)
            if len(bars)<30:
                raise ValueError("insufficient history")
            out["timeframes"][interval]={"status":"ok","bars":bars}
        except (OSError,ValueError,TypeError,KeyError,TimeoutError) as exc:
            out["timeframes"][interval]={"status":"unavailable","bars":[]}
            out["errors"][interval]=type(exc).__name__
    out["status"]="verified" if all(x["status"]=="ok" for x in out["timeframes"].values()) else "partial"
    return out

def main():
    record=collect()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("Binance candles:",record["status"],"frames:",[k for k,v in record["timeframes"].items() if v["status"]=="ok"])

if __name__=="__main__":
    main()
