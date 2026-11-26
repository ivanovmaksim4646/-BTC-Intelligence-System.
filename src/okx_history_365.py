"""Paginated public OKX history, strict complete coverage or fail."""
import datetime as dt
import json,time
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.parse import urlencode
from math import isfinite
API="https://www.okx.com/api/v5/market/history-candles"
STEPS={"5m":300,"1h":3600,"4h":14400}
def page(tf,after):
    url=API+"?"+urlencode({"instId":"BTC-USDT-SWAP","bar":{"5m":"5m","1h":"1H","4h":"4H"}[tf],"after":after,"limit":100})
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={"User-Agent":"BTC-Intelligence/2"}),timeout=25) as f:
                p=json.load(f)
            if str(p.get("code"))!="0" or not isinstance(p.get("data"),list):raise ValueError("OKX response")
            return p["data"]
        except (OSError,ValueError):
            if attempt==2:raise
            time.sleep(2**attempt)
def download(tf,start,end,getter=page):
    step=STEPS[tf]; cursor=end*1000; rows={}
    while cursor>start*1000:
        data=getter(tf,cursor)
        if not data:raise ValueError("history ended early")
        times=[]
        for x in data:
            t=int(x[0]);times.append(t)
            if t>=cursor or t%(step*1000):raise ValueError("bad pagination")
            t//=1000
            if not start<=t<end:continue
            if str(x[8])!="1":raise ValueError("unclosed candle")
            o,h,l,c=map(float,x[1:5])
            if not all(isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h:raise ValueError("bad OHLC")
            bar=dict(t=t,o=o,h=h,l=l,c=c)
            if t in rows and rows[t]!=bar:raise ValueError("conflicting duplicate")
            rows[t]=bar
        cursor=min(times)
        if getter is page:time.sleep(.12)
    if sorted(rows)!=list(range(start,end,step)):raise ValueError("incomplete coverage")
    return [rows[t] for t in sorted(rows)]
def collect(days=365, getter=page):
    if not 1<=days<=365:raise ValueError("days")
    end=int(dt.datetime.now(dt.timezone.utc).timestamp())//14400*14400
    start=end-days*86400
    frames={}
    for tf,step in STEPS.items():
        frames[tf]={"status":"ok","bars":download(tf,start-300*step,end,getter)}
        print(tf,len(frames[tf]["bars"]),flush=True)
    return {"source":"OKX BTC-USDT-SWAP","status":"verified","start":start,"end":end,"days":days,"timeframes":frames}
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--days",type=int,default=365);p.add_argument("--out",default="data/BTC-okx-history-365.json");a=p.parse_args()
    Path(a.out).write_text(json.dumps(collect(a.days),separators=(",",":")))
