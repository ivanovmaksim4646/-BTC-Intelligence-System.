"""Bounded public OKX history-trades pagination feasibility probe; no orders."""
import json
import time
import urllib.request
import urllib.parse
from decimal import Decimal
from pathlib import Path

def request(path, params):
    url="https://www.okx.com/api/v5/"+path+"?"+urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"BTC-Intelligence-research/1.0"}),timeout=10) as r:
        obj=json.load(r)
    if obj.get("code")!="0" or not isinstance(obj.get("data"),list):
        raise ValueError("OKX response not successful")
    return obj["data"]

def probe(inst, fetch, end, max_pages=180):
    start=end-300000
    cursor=None
    seen=set()
    buy=sell=Decimal(0)
    oldest=newest=None
    pages=0
    reason="page_budget"
    for _ in range(max_pages):
        rows=fetch(cursor)
        pages+=1
        if not rows:
            reason="empty_page"
            break
        ids=[int(r["tradeId"]) for r in rows]
        ts=[int(r["ts"]) for r in rows]
        if any(a<=b for a,b in zip(ids,ids[1:])) or any(a<b for a,b in zip(ts,ts[1:])):
            raise ValueError("unexpected page ordering")
        if cursor is not None and ids[0]>=cursor:
            raise ValueError("cursor failed to advance")
        for r,i,t in zip(rows,ids,ts):
            if r["instId"]!=inst or i in seen or r["side"] not in ("buy","sell"):
                raise ValueError("invalid or duplicate trade")
            size=Decimal(r["sz"])
            if not size.is_finite() or size<=0:
                raise ValueError("invalid size")
            seen.add(i)
            oldest=t if oldest is None else min(t,oldest)
            newest=t if newest is None else max(t,newest)
            if start<=t<end:
                if r["side"]=="buy": buy+=size
                else: sell+=size
        cursor=ids[-1]
        if oldest<start:
            reason="start_crossed"
            break
    return {"instrument":inst,"pages":pages,"records":len(seen),"start_ms":start,"end_ms":end,
            "oldest_ms":oldest,"newest_ms":newest,"reason":reason,
            "both_time_boundaries_observed":oldest is not None and oldest<start and newest>=end,
            "observed_buy_native":str(buy),"observed_sell_native":str(sell),
            "observed_delta_native":str(buy-sell),"unit":"BTC" if inst=="BTC-USDT" else "contracts",
            "complete_delta_btc":None,"complete_cvd_btc":None,"completeness_verified":False}

def main():
    end=int(time.time()*1000)//300000*300000
    results=[]
    for inst in ("BTC-USDT","BTC-USDT-SWAP"):
        def fetch(cursor):
            time.sleep(.25)
            p={"instId":inst,"type":"1","limit":"100"}
            if cursor is not None:p["after"]=str(cursor)
            return request("market/history-trades",p)
        began=time.monotonic()
        try:
            result=probe(inst,fetch,end,max_pages=500 if inst=="BTC-USDT-SWAP" else 180)
        except Exception as e:
            result={"instrument":inst,"error":str(e),"completeness_verified":False,
                    "complete_delta_btc":None,"complete_cvd_btc":None}
        result["elapsed_seconds"]=round(time.monotonic()-began,2)
        results.append(result)
    out={"classification":"bounded_rest_pagination_research_only","results":results}
    Path("data").mkdir(exist_ok=True)
    Path("data/BTC-okx-rest-pagination-probe.json").write_text(json.dumps(out,indent=2))
    print(json.dumps(out))
if __name__=="__main__":main()
