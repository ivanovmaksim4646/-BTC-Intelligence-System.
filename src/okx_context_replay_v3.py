"""Re-evaluate baseline entries on identical frozen dates, append causal context."""
import json
from bisect import bisect_right
from pathlib import Path
from src import okx_history_365 as loader
from src.okx_historical_replay_v2 import replay
from src.okx_context_research_v3 import context,cohorts
from src.rr_outcome_research_v1 import aggregate
START=1764158400
END=1795694400
def main():
    # Keep baseline dates unchanged. D1 UTC uses its own aligned boundaries.
    frames={tf:{"status":"ok","bars":loader.download(tf,START-300*step,END)} for tf,step in loader.STEPS.items()}
    h={"source":"OKX BTC-USDT-SWAP","status":"verified","start":START,"end":END,"days":365,"timeframes":frames}
    base=replay(h)
    if base["entry_count"]!=139:raise ValueError("baseline changed; inspect revised history before comparison")
    loader.STEPS["1d"]=86400
    # page wrapper uses original endpoint with explicit UTC daily interval.
    import urllib.request,urllib.parse,time
    def daily(tf,after):
        url=loader.API+"?"+urllib.parse.urlencode({"instId":"BTC-USDT-SWAP","bar":"1Dutc","after":after,"limit":100})
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"BTC-Intelligence/3"}),timeout=25) as f:p=json.load(f)
        if p.get("code")!="0":raise ValueError("daily response")
        time.sleep(.15)
        return p["data"]
    frames["1d"]={"bars":loader.download("1d",START//86400*86400-300*86400,END//86400*86400,daily)}
    steps={"5m":300,"1h":3600,"4h":14400,"1d":86400}
    close_times={tf:[b["t"]+step for b in frames[tf]["bars"]] for tf,step in steps.items()}
    for e in base["entries"]:
        prefix={}
        for tf in steps:
            j=bisect_right(close_times[tf],e["entry_close_utc"])
            prefix[tf]=frames[tf]["bars"][max(0,j-299):j]
        e["context"]=context(e,prefix)
    stats={}
    for name,rows in cohorts(base["entries"]).items():
        stats[name]={"count":len(rows),"fixed_rr":aggregate(rows),"by_sample":{s:aggregate([e for e in rows if e["sample"]==s]) for s in ("in_sample","holdout")}}
    out={"classification":"exploratory_same_period_not_independent_validation","baseline_count":139,"start":START,"end":END,"cohorts":stats,"entries":base["entries"],"trade_signal":None}
    Path("data/BTC-okx-context-replay-v3.json").write_text(json.dumps(out,indent=2))
    print("CONTEXT REPLAY",json.dumps({k:v for k,v in out.items() if k!="entries"}),flush=True)
if __name__=="__main__":main()
