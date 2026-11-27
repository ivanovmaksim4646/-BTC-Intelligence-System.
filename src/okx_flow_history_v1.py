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
def collect_one(inst,end,max_runtime_seconds=180,max_pages_override=None):
    began=time.monotonic()
    def fetch(cursor):
        # Two parallel instruments, each at most four requests/s before latency.
        if time.monotonic()-began>max_runtime_seconds:raise TimeoutError("bounded collection deadline")
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
        r=probe(inst,fetch,end,max_pages=max_pages_override if max_pages_override is not None else (500 if inst.endswith("SWAP") else 180))
        # The recent-candles endpoint only returns the latest bars. A
        # retrospective gap up to four hours old must query the historical
        # endpoint using a timestamp cursor or reconciliation will fail
        # simply because the target candle is no longer in the latest ten.
        current_end=int(time.time()*1000)//M5*M5
        if current_end-end>8*M5:
            candles=request("market/history-candles",
                            {"instId":inst,"bar":"5m","after":str(end+M5),"limit":"10"})
        else:
            candles=request("market/candles",{"instId":inst,"bar":"5m","limit":"10"})
        meta=request("public/instruments",{"instType":"SWAP","instId":inst}) if inst.endswith("SWAP") else []
        r=reconcile(r,candles,meta)
    except Exception as exc:
        r={"instrument":inst,"end_ms":end,"volume_reconciled":False,"error":type(exc).__name__}
    r["elapsed_seconds"]=round(time.monotonic()-began,2)
    return r
def backfill_target(rows,end,max_age_buckets=48,instrument="BTC-USDT"):
    """Nearest missing recent Spot M5; at most one extra REST window per sync.

    Do not retry the just-closed bucket in the same run. Missing data is
    never inferred; only the existing merge() verifier can persist it.
    """
    confirmed={r.get("end_ms") for r in rows
               if isinstance(r,dict) and r.get("instrument")==instrument
               and r.get("volume_reconciled") is True}
    for t in range(end-M5,end-(max_age_buckets+1)*M5,-M5):
        if t not in confirmed:
            return t
    return None

def spot_backfill_target(rows,end,max_age_buckets=48):
    return backfill_target(rows,end,max_age_buckets)

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
    # One bounded Spot backfill per sync: no unbounded retries or fabricated
    # historical CVD. Backfill reuses the exact same provenance gates.
    target=spot_backfill_target(old+results,end)
    swap_target=backfill_target(old+results,end,instrument="BTC-USDT-SWAP")
    # Independent instruments can recover concurrently; preserve existing
    # deadlines, pagination and exact-volume verification.
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(collect_one,"BTC-USDT",target,max_runtime_seconds=35,max_pages_override=100) if target is not None else None
        b=pool.submit(collect_one,"BTC-USDT-SWAP",swap_target,max_runtime_seconds=180,max_pages_override=500) if swap_target is not None else None
        backfill=a.result() if a else None
        swap_backfill=b.result() if b else None
    rows=merge(old,results+[r for r in (backfill,swap_backfill) if r is not None],end)
    out={"classification":"volume_reconciled_rest_research_only","end_ms":end,"results":results,
         "spot_backfill":{"target_end_ms":target,
                          "volume_reconciled":backfill.get("volume_reconciled") if backfill else None,
                          "error":backfill.get("error") if backfill else None},
         "futures_backfill":{"target_end_ms":swap_target,
                             "volume_reconciled":swap_backfill.get("volume_reconciled") if swap_backfill else None,
                             "error":swap_backfill.get("error") if swap_backfill else None},
         "history_count":len(rows),"instruments":summarize(rows,end),"trade_signal":None}
    write(HISTORY,rows);write(CURRENT,out)
    print("PERSISTENT FLOW",json.dumps(out),flush=True)
if __name__=="__main__":main()
