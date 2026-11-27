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
def session_flow(index, end):
    """Session-to-date aggregates for a fully observed window, by local market clock."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    out = {}
    for label, zone, hour, minute, minutes in (
        ("Asia_window", "Europe/Warsaw", 2, 0, 360),
        ("London_window", "Europe/London", 8, 0, 120),
        ("US_cash_open_window", "America/New_York", 9, 30, 180),
    ):
        last = datetime.fromtimestamp((end - 1) / 1000, ZoneInfo(zone))
        start = last.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
        if last < start:
            start -= timedelta(days=1)
        first = int(start.timestamp()) * 1000
        stop = min(end, int((start + timedelta(minutes=minutes)).timestamp()) * 1000)
        needed = range(first + M5, stop + 1, M5)
        buckets = [index[t] for t in needed if t in index and index[t].get("volume_reconciled") is True]
        full = len(buckets) == len(needed) and bool(buckets)
        volume = sum((decimal(r["volume_btc_reconciled"]) for r in buckets), Decimal(0))
        quote_ok = all(r.get("quote_volume_usdt") is not None for r in buckets)
        quote = sum((decimal(r["quote_volume_usdt"]) for r in buckets), Decimal(0)) if quote_ok else None
        out[label] = dict(start_ms=first, end_ms=stop, timezone=zone,
                          required_m5=len(needed), reconciled_m5=len(buckets),
                          session_delta_btc_reconciled=str(sum(decimal(r["delta_btc_reconciled"]) for r in buckets)) if full else None,
                          vwap_usdt=str(quote / volume) if full and quote is not None and volume else None)
    return out

def summarize(rows,end):
    out={}
    for inst in INSTRUMENTS:
        by_end={r["end_ms"]:r for r in rows if r["instrument"]==inst}
        t=end;chain=[]
        while t in by_end:
            chain.append(by_end[t]);t-=M5
        out[inst]={"rolling_windows":aggregate(rows,end,inst),"sessions":session_flow(by_end,end),"consecutive_m5":len(chain),
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

def rotating_backfill_target(rows,end,instrument,previous_target=None):
    """Try another missing H4 bucket after a failed attempt, without starving recent gaps."""
    confirmed={r["end_ms"] for r in rows if isinstance(r,dict)
               and r.get("instrument")==instrument and r.get("volume_reconciled") is True}
    gaps=[t for t in range(end-M5,end-48*M5,-M5) if t not in confirmed]
    if not gaps:return None
    if previous_target in gaps:
        return gaps[(gaps.index(previous_target)+1)%len(gaps)]
    return gaps[0]

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
    # Retry a different gap after a failed attempt. Run instruments in
    # parallel within the existing per-instrument request pacing.
    try:
        previous=json.loads(CURRENT.read_text())
    except (OSError,ValueError):
        previous={}
    def repair(inst,key,seconds,pages):
        p=previous.get(key) or {}
        prior=p.get("target_end_ms") if p.get("volume_reconciled") is False else None
        target=rotating_backfill_target(old+results,end,inst,prior)
        result=collect_one(inst,target,max_runtime_seconds=seconds,max_pages_override=pages) if target is not None else None
        return target,result
    with ThreadPoolExecutor(max_workers=2) as pool:
        spot=pool.submit(repair,"BTC-USDT","spot_backfill",60,180)
        swap=pool.submit(repair,"BTC-USDT-SWAP","futures_backfill",180,500)
        target,backfill=spot.result()
        swap_target,swap_backfill=swap.result()
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
