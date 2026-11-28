"""Advisory analysis of existing exchange observations; no new API requests."""
import math, json, datetime as dt
from pathlib import Path
from src.okx_liquidity_history_v1 import check_history_row
DATA=Path("data")
def flow_segments(rows,end_ms):
    result={}
    for name in ("BTC-USDT","BTC-USDT-SWAP"):
        by={};conflicts=set()
        for row in rows:
            if row.get("instrument")!=name or row.get("volume_reconciled") is not True:continue
            t=row.get("end_ms")
            if type(t) is not int or t%300000 or row.get("start_ms")!=t-300000 or t>end_ms:continue
            try:d,v,o,c=(float(row[k]) for k in ("delta_btc_reconciled","volume_btc_reconciled","open_usdt","close_usdt"))
            except (KeyError,ValueError,TypeError):continue
            if not all(map(math.isfinite,(d,v,o,c))) or v<abs(d) or min(o,c)<=0:continue
            val=(d,v,o,c)
            if t in by and by[t]!=val:conflicts.add(t)
            by[t]=val
        points=[];total=0.;t=end_ms
        while t in by and t not in conflicts and len(points)<288:
            points.append((t,*by[t]));t-=300000
        points.reverse()
        windows={}
        for n in (1,3,12,48):
            if len(points)<n:continue
            p=points[-n:];delta=sum(x[1] for x in p);vol=sum(x[2] for x in p)
            ret=p[-1][4]/p[0][3]-1
            windows[str(n*5)+"m"]={"delta_btc":delta,"volume_btc":vol,"price_return_pct":ret*100,
                "divergence_candidate":("price_down_delta_positive" if ret<0 and delta>0 else "price_up_delta_negative" if ret>0 and delta<0 else None)}
        series=[]
        for t,d,v,o,c in points:
            total+=d
            series.append({"end_ms":t,"cumulative_reconciled_delta_btc":total,"close_usdt":c})
        result[name]={"classification":"segment_cumulative_reconciled_delta_not_sequence_certified_cvd",
                      "consecutive_m5":len(points),"windows":windows,"series":series,"conflicts":len(conflicts)}
    return result
def liquidity(rows,now_ms):
    by={};conflicts=set()
    for r in rows:
        if not check_history_row(r):continue
        t=r["book_timestamp_ms"]
        if not 0<=now_ms-t<=86400000:continue
        if t in by and by[t]!=r:conflicts.add(t)
        by[t]=r
    points=[]
    for t,r in sorted(by.items()):
        if t in conflicts:continue
        points.append({"timestamp_ms":t,"bid_depth_btc":r["bid_depth_btc"],"ask_depth_btc":r["ask_depth_btc"],
         "mid_usdt":(r["best_bid"]+r["best_ask"])/2,"bid_walls":r["bid_walls"],"ask_walls":r["ask_walls"]})
    gaps=[b["timestamp_ms"]-a["timestamp_ms"] for a,b in zip(points,points[1:])]
    return {"classification":"sampled_top3_resting_liquidity_not_liquidation_heatmap","samples":len(points),
        "excluded_conflicts":len(conflicts),"max_gap_seconds":max(gaps,default=0)/1000,
        "points":points,"liquidation_heatmap":None}
def main():
    now=dt.datetime.now(dt.timezone.utc);ms=int(now.timestamp()*1000);end=ms//300000*300000
    rows=json.loads((DATA/"BTC-okx-reconciled-m5-history.json").read_text())
    book=[json.loads(line) for line in (DATA/"BTC-okx-liquidity-history-v1.jsonl").read_text().splitlines() if line.strip()]
    out={"classification":"advisory_only","generated_at_utc":now.isoformat(),"flow":flow_segments(rows,end),
         "liquidity":liquidity(book,ms),"trade_signal":None}
    (DATA/"BTC-advisory-history-v1.json").write_text(json.dumps(out,allow_nan=False))
    print("advisory history", {k:v["consecutive_m5"] for k,v in out["flow"].items()}, "liquidity samples",out["liquidity"]["samples"])
if __name__=="__main__":main()
