"""Persistent reconciled M5 research history, independent of production signals."""
import json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from src.okx_rest_pagination_probe import probe,request
from src.okx_flow_reconcile import aggregate,reconcile,INSTRUMENTS,M5,decimal
DATA=Path("data")
HISTORY=DATA/"BTC-okx-reconciled-m5-history.json"
CURRENT=DATA/"BTC-okx-reconciled-flow-current.json"
def merge(old,new,end):
    result={}
    for r in old+new:
        if r.get("instrument") not in INSTRUMENTS or r.get("volume_reconciled") is not True:continue
        t=r["end_ms"]
        if type(t) is not int or t%M5 or r["start_ms"]!=t-M5 or t>end:raise ValueError("invalid bucket")
        d=decimal(r["delta_btc_reconciled"]);v=decimal(r["volume_btc_reconciled"])
        if v<abs(d):raise ValueError("invalid volume")
        key=(r["instrument"],t)
        if key in result:
            prev=result[key]
            if any(decimal(prev[k])!=decimal(r[k]) for k in ("delta_btc_reconciled","volume_btc_reconciled")):
                raise ValueError("conflicting reconciled bucket")
        else:result[key]=r
    return [result[k] for k in sorted(result) if k[1]>end-7*86400000]
def summarize(rows,end):
    out={}
    for inst in INSTRUMENTS:
        by_end={r["end_ms"]:r for r in rows if r["instrument"]==inst}
        t=end;chain=[]
        while t in by_end:
            chain.append(by_end[t]);t-=M5
        out[inst]={"rolling_windows":aggregate(rows,end,inst),"consecutive_m5":len(chain),
            "segment_start_ms":t if chain else None,
            "segment_cvd_btc_reconciled":str(sum((decimal(r["delta_btc_reconciled"]) for r in chain),Decimal(0))) if chain else None,
            "complete_cvd_btc":None,"classification":"volume_reconciled_not_sequence_certified"}
    return out
def collect_one(inst,end):
    began=time.monotonic()
    def fetch(cursor):
        # Two parallel instruments, each at most four requests/s before latency.
        if time.monotonic()-began>180:raise TimeoutError("bounded collection deadline")
        time.sleep(.25)
        p={"instId":inst,"type":"1","limit":"100"}
        if cursor is None:
            # Pagination type=2 returns trades STRICTLY earlier than the given
            # timestamp. BTC Spot can have no print in the first second after
            # M5 close; a +1s cursor then excludes all post-close trades and
            # fails the independent upper-boundary evidence gate.
            #
            # Seed Spot from a bounded post-close margin, while preserving
            # type=1 trade-id pagination and exact closed-candle volume match.
            # If no actual post-close trade exists yet, provenance stays
            # incomplete instead of inventing boundary coverage.
            margin_ms=60000 if inst=="BTC-USDT" else 1000
            p.update(type="2", after=str(end+margin_ms))
        else:p["after"]=str(cursor)
        return request("market/history-trades",p)
    try:
        r=probe(inst,fetch,end,max_pages=500 if inst.endswith("SWAP") else 180)
        candles=request("market/candles",{"instId":inst,"bar":"5m","limit":"10"})
        meta=request("public/instruments",{"instType":"SWAP","instId":inst}) if inst.endswith("SWAP") else []
        r=reconcile(r,candles,meta)
    except Exception as exc:
        r={"instrument":inst,"end_ms":end,"volume_reconciled":False,"error":type(exc).__name__}
    r["elapsed_seconds"]=round(time.monotonic()-began,2)
    return r
def write(path,obj):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,indent=2)+"\n")
    tmp.replace(path)
def main():
    DATA.mkdir(exist_ok=True)
    end=int(time.time()*1000)//M5*M5
    old=json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    if not isinstance(old,list):raise ValueError("invalid history")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda i:collect_one(i,end),INSTRUMENTS))
    rows=merge(old,results,end)
    out={"classification":"volume_reconciled_rest_research_only","end_ms":end,"results":results,
         "history_count":len(rows),"instruments":summarize(rows,end),"trade_signal":None}
    write(HISTORY,rows);write(CURRENT,out)
    print("PERSISTENT FLOW",json.dumps(out),flush=True)
if __name__=="__main__":main()
