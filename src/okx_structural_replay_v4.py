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
    candidate_count=base["entry_count"]
    base["entries"]=[e for e in base["entries"] if (abs(e["take_profit"]-e["entry"])-e["entry"]*e["total_cost_bps"]/10000)/(abs(e["entry"]-e["stop_loss"])+e["entry"]*e["total_cost_bps"]/10000)>=2]
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
        # Aggregate only fully closed M15 candles from causal M5 prefix.
        m15=[]
        for i in range(len(prefix["5m"])-2):
            a,b,c=prefix["5m"][i:i+3]
            if a["t"]%900==0 and c["t"]+300<=e["entry_close_utc"]:
                m15.append({"t":a["t"],"o":a["o"],"h":max(a["h"],b["h"],c["h"]),"l":min(a["l"],b["l"],c["l"]),"c":c["c"]})
        from src.okx_context_research_v3 import trend
        e["context"]["m15_structure"]=trend(m15)
    # Use actual preconfirmed liquidity targets; normalize R to total stop risk.
    for e in base["entries"]:
        cost=e["entry"]*e["total_cost_bps"]/10000
        risk=abs(e["entry"]-e["stop_loss"])+cost
        o=e["liquidity_target_outcome"]
        if o["status"]=="target_first": o["net_r"]=(abs(e["take_profit"]-e["entry"])-cost)/risk
        elif o["status"]=="stop_first": o["net_r"]=-1.0
        e["outcomes"]={"2.0":o}
    def portfolio(rows):
        balance=peak=1000.0
        drawdown=0.0
        busy=0
        wins=losses=skipped=unresolved=0
        results=[]
        for e in sorted(rows,key=lambda e:(e["entry_close_utc"],e["entry_id"])):
            if e["entry_close_utc"]<busy:
                skipped+=1
                continue
            o=e["liquidity_target_outcome"]
            if o["status"]=="unresolved":
                busy=base["split"] if e["sample"]=="in_sample" else END
                unresolved+=1
                continue
            busy=o["hit_time"]
            r=o["net_r"] if o["status"]!="ambiguous_same_candle" else -1.0
            if r is None: raise ValueError("invalid outcome")
            balance+=balance*0.01*r
            peak=max(peak,balance)
            drawdown=max(drawdown,(peak-balance)/peak)
            wins+=r>0
            losses+=r<0
            results.append(r)
        return {"starting_balance":1000,"ending_balance":balance,"pnl":balance-1000,
                "max_realized_drawdown":drawdown,"wins":wins,"losses":losses,
                "win_rate":wins/len(results) if results else None,
                "expectancy_net_r":sum(results)/len(results) if results else None,
                "overlap_skipped":skipped,"unresolved":unresolved}
    stats={}
    groups=cohorts(base["entries"])
    groups["m15_aligned"]=[e for e in base["entries"] if e["context"]["m15_structure"]==("bullish" if e["direction"]=="long" else "bearish")]
    for name,rows in groups.items():
        stats[name]={"count":len(rows),"portfolio":portfolio(rows),"actual_target":aggregate(rows,rr_levels=(2.0,))["2.0"],"by_sample":{s:portfolio([e for e in rows if e["sample"]==s]) for s in ("in_sample","holdout")}}
    out={"classification":"exploratory_same_period_not_independent_validation","candidate_count":candidate_count,"eligible_count":len(base["entries"]),"minimum_net_rr":2,"trade_quota":None,"start":START,"end":END,"cohorts":stats,"entries":base["entries"],"trade_signal":None}
    Path("data/BTC-okx-structural-replay-v4.json").write_text(json.dumps(out,indent=2))
    print("CONTEXT REPLAY",json.dumps({k:v for k,v in out.items() if k!="entries"}),flush=True)
if __name__=="__main__":main()
