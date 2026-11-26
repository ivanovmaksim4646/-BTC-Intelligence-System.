"""Rolling causal replay using the shared structural rules; never forward entries."""
import datetime as dt
import json
from bisect import bisect_right
from collections import Counter
from pathlib import Path
try:
    from src.okx_entry_evidence_gate_v1 import evaluate_historical,VENUE
    from src.rr_outcome_research_v1 import compare_rr_paths,aggregate
    from src.okx_outcome_tracker_v1 import check_bar
except ModuleNotFoundError:
    from okx_entry_evidence_gate_v1 import evaluate_historical,VENUE
    from rr_outcome_research_v1 import compare_rr_paths,aggregate
    from okx_outcome_tracker_v1 import check_bar
STEPS={"5m":300,"1h":3600,"4h":14400}
def replay(history):
    if history["source"]!=VENUE or history["status"]!="verified":raise ValueError("source")
    start,end=history["start"],history["end"]
    if end-start!=history["days"]*86400:raise ValueError("duration")
    frames={tf:history["timeframes"][tf]["bars"] for tf in STEPS}
    closes={}
    for tf,step in STEPS.items():
        b=frames[tf]
        if not all(check_bar(x) for x in b) or [x["t"] for x in b]!=list(range(start-300*step,end,step)):raise ValueError("coverage")
        closes[tf]=[x["t"]+step for x in b]
    m5=frames["5m"]; records=[];funnel=Counter();n=0
    split=start+(history["days"]*2//3)*86400
    for i,b in enumerate(m5):
        close=b["t"]+300
        if not start<close<=end:continue
        now=dt.datetime.fromtimestamp(close,dt.timezone.utc)
        prefix={}
        for tf in STEPS:
            j=bisect_right(closes[tf],close)
            prefix[tf]={"status":"ok","bars":frames[tf][max(0,j-299):j]}
        r=evaluate_historical({"source":VENUE,"status":"verified","collected_at_utc":now.isoformat(),"timeframes":prefix},now)
        n+=1
        funnel.update({k:v for k,v in r["diagnostics"].items() if k!="latest_m5_close_s" and type(v) is int})
        for e in r["paper_entries"]:
            # Freeze split boundary; in-sample outcomes cannot use holdout bars.
            limit=split if close<=split else end
            future=[{**x,"t":x["t"]+300,"closed":True} for x in m5[i+1:bisect_right(closes["5m"],limit)]]
            p=compare_rr_paths(e["direction"],e["entry"],e["stop_loss"],close,future,total_cost_bps=e["total_cost_bps"])
            rr=abs(e["take_profit"]-e["entry"])/abs(e["entry"]-e["stop_loss"])
            actual=compare_rr_paths(e["direction"],e["entry"],e["stop_loss"],close,future,target_rs=(rr,),total_cost_bps=e["total_cost_bps"])
            records.append({**e,"sample":"in_sample" if close<=split else "holdout","outcomes":p["outcomes"],"liquidity_target_outcome":actual["outcomes"][str(rr)]})
    if n!=history["days"]*288:raise ValueError("evaluated count")
    return {"classification":"historical_research_only","performance_verified":False,"trade_signal":None,"source":VENUE,"start":start,"end":end,"split":split,"days":history["days"],"bars_evaluated":n,"funnel":dict(funnel),"entry_count":len(records),"statistics":aggregate(records),"by_direction":{d:aggregate([e for e in records if e["direction"]==d]) for d in ("long","short")},"by_sample":{s:aggregate([e for e in records if e["sample"]==s]) for s in ("in_sample","holdout")},"entries":records}
if __name__=="__main__":
    h=json.loads(Path("data/BTC-okx-history-365.json").read_text())
    r=replay(h)
    Path("data/BTC-okx-historical-replay-v2.json").write_text(json.dumps(r,indent=2))
    print("REPLAY V2",json.dumps({k:v for k,v in r.items() if k!="entries"}),flush=True)
