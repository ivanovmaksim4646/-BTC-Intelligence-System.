"""Exploratory v5 subset: causal candle replay, no historical order-flow claims."""
import json
from datetime import datetime, timezone
from statistics import median
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path
from src import okx_history_365 as loader
from src.okx_structural_replay_v4 import START,END
from src.okx_market_context_v1 import confirmed_pivots
from src.okx_context_research_v3 import trend
from src.okx_entry_evidence_gate_v1 import prior_poi_zones
from src.structure import structural_shift
from src.okx_v5_context_rules import contextual_shift,inside_deviation,rr_band,confluence,trend_relation
from src.strategy_models_v1 import scan_qm

def aggregate(bars,step):
    out=[]
    for i in range(0,len(bars)):
        a=bars[i]
        if a["t"]%step:continue
        n=step//300
        b=bars[i:i+n]
        if len(b)!=n or b[-1]["t"]!=a["t"]+step-300:continue
        out.append(dict(t=a["t"],o=a["o"],h=max(x["h"] for x in b),l=min(x["l"] for x in b),c=b[-1]["c"]))
    return out

def run():
    frames={tf:loader.download(tf,START-300*s,END) for tf,s in loader.STEPS.items()}
    frames["15m"]=aggregate(frames["5m"],900)
    frames["1d"]=aggregate(frames["4h"],86400)
    steps={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}
    closes={tf:[x["t"]+steps[tf] for x in b] for tf,b in frames.items()}
    m5=frames["5m"]
    rows=[]
    rejected=defaultdict(int)
    consumed=set()
    for tf in ("15m","5m"):
        step=steps[tf]; bars=frames[tf]
        for i in range(40,len(bars)):
            b=bars[i]; at=b["t"]+step
            if not START<at<=END:continue
            p=bars[max(0,i-80):i]; window=p+[b]
            s=structural_shift(window)
            dev=inside_deviation(p[-2],p[-1],b)
            qm=[]
            for q in scan_qm(window):
                if b["t"]<q["structural_extreme_time"]+3*step:continue
                level=q["left_shoulder"];d=q["direction"]
                def retest(x):
                    return x["l"]<=level<=x["h"] and abs(x["c"]-level)/level<=.001 and (x["c"]>level if d=="long" else x["c"]<level)
                if retest(b) and not any(retest(x) for x in p if x["t"]>=q["structural_extreme_time"]+3*step):qm.append(q)
            if not (s or dev or qm):continue
            hframes={}
            for k in ("1h","4h","1d"):
                j=bisect_right(closes[k],b["t"])
                hframes[k]=frames[k][max(0,j-120):j]
            for d in ("long","short"):
                up=d=="long"; events=[]; tags=[]; levels=[]
                for k,h in hframes.items():
                    for z in prior_poi_zones(h,steps[k],b["t"],d):
                        touch=[x for x in p[-12:] if x["t"]>=z["available_at"] and x["l"]<=z["high"] and x["h"]>=z["low"]]
                        if touch and not any((x["c"]<z["low"] if up else x["c"]>z["high"]) for x in window if x["t"]>=touch[0]["t"]):
                            events.append(dict(direction=d,kind="POI",tf=k,known_at=touch[-1]["t"]+step,first_touch=touch[0]["t"],valid=True,episode=(k,z["available_at"],z["low"],z["high"])))
                            tags.append(k+":"+z["kind"])
                    hi,lo=confirmed_pivots(h)
                    for pivot in (hi if up else lo):
                        v=pivot["price"]
                        if (v>b["c"] if up else v<b["c"]) and not any((x["h"]>=v if up else x["l"]<=v) for x in h if x["t"]>pivot["t"]) and not any((x["h"]>=v if up else x["l"]<=v) for x in m5[max(0,bisect_right(closes["5m"],h[-1]["t"]+steps[k])):bisect_right(closes["5m"],at)]):
                            levels.append(v)
                for j in range(max(5,len(p)-12),len(p)):
                    hi,lo=confirmed_pivots(p[:j]); piv=lo if up else hi
                    if piv:
                        v=piv[-1]["price"]; x=p[j]
                        if (x["l"]<v<x["c"] if up else x["h"]>v>x["c"]):
                            events.append(dict(direction=d,kind="internal_sweep",known_at=x["t"]+step,extreme=x["l"] if up else x["h"],valid=True,episode=(tf,piv[-1]["t"],v)))
                # Prior UTC day extremes: first sweep of a known external level.
                days=hframes["1d"]
                if days:
                    day=days[-1]; v=day["l"] if up else day["h"]
                    since=[x for x in m5[bisect_right(closes["5m"],day["t"]+86400):bisect_right(closes["5m"],b["t"])]]
                    hits=[x for x in since if (x["l"]<v if up else x["h"]>v)]
                    if hits and hits[0]["t"]>=p[-12]["t"] and (hits[0]["c"]>v if up else hits[0]["c"]<v):
                        x=hits[0]
                        events.append(dict(direction=d,kind="external_sweep",known_at=x["t"]+300,valid=True,extreme=x["l"] if up else x["h"],episode=("PD",day["t"],v)))
                strong=[e for e in events if e["kind"] in ("POI","external_sweep")]
                if not strong:
                    rejected["no_mtf_htf_or_external_context"]+=1;continue
                shift=bool(s and s["kind"].startswith("bullish" if up else "bearish") and contextual_shift(d,b,p,s["break_level"],strong))
                models=[]
                if shift:models.append("context_shift")
                qmatches=[]
                for q in qm:
                    if q["direction"]!=d:continue
                    head=next((x for x in p if x["t"]==q["head_time"]),None)
                    if head is None:continue
                    head_context=[e for e in strong if e["kind"]=="POI" and e["episode"][1]<=head["t"] and e["first_touch"]<=head["t"] and head["l"]<=e["episode"][3] and head["h"]>=e["episode"][2]]
                    if not head_context:continue
                    if any((x["l"]<q["head_extreme"] if up else x["h"]>q["head_extreme"]) for x in window if x["t"]>head["t"]):continue
                    qmatches.append(q)
                if qmatches:models.append("POI_QM")
                # Deviation must reclaim the mother midpoint with a directional body
                # at a higher timeframe context, rather than a random inside bar.
                mid=(p[-2]["h"]+p[-2]["l"])/2
                if dev==d and (b["c"]>max(mid,b["o"]) if up else b["c"]<min(mid,b["o"])) and abs(b["c"]-b["o"])>=median(abs(x["c"]-x["o"]) for x in p[-20:]):
                    models.append("inside_deviation")
                if tf=="5m" and "context_shift" in models:models.remove("context_shift")
                if not models or not levels:continue
                # Require a fresh directional structural event, not a recurring old shift.
                if shift and not (p[-1]["c"]<=s["break_level"]<b["c"] if up else p[-1]["c"]>=s["break_level"]>b["c"]):
                    models.remove("context_shift")
                if not models:
                    rejected["stale_shift"]+=1;continue
                # M5 is experimental; keep independent statistics, not combined entries.
                # A previously traded context must not generate repeated candidates.
                keys={(tf,d,e["episode"]) for e in strong}
                if not keys or keys & consumed:
                    rejected["reused_context"]+=1;continue
                entry=b["c"]
                anchors=[e["extreme"] for e in strong if "extreme" in e]
                anchors += [q["head_extreme"] for q in qmatches]
                anchors += [b["l"] if up else b["h"]] if dev==d and "inside_deviation" in models else []
                anchors += [min(x["l"] for x in window if x["t"]>=e["first_touch"]) if up else max(x["h"] for x in window if x["t"]>=e["first_touch"]) for e in strong if e["kind"]=="POI"]
                if not anchors:continue
                stop=min(anchors)*.9997 if up else max(anchors)*1.0003
                if not (stop<entry if up else stop>entry):continue
                cost=entry*.0014; risk=abs(entry-stop)+cost
                target=min(levels,key=lambda v:abs(v-entry))
                rr=(abs(target-entry)-cost)/risk
                band=rr_band(rr)
                if band is None:continue
                split=START+243*86400
                limit=split if at<=split else END
                future=m5[bisect_right(closes["5m"],at):bisect_right(closes["5m"],limit)]
                def outcome(tp):
                    for x in future:
                        sl=x["l"]<=stop if up else x["h"]>=stop
                        hit=x["h"]>=tp if up else x["l"]<=tp
                        if sl or hit:
                            exit_price=(min(stop,x["o"]) if up else max(stop,x["o"])) if sl else tp
                            return dict(r=((exit_price-entry)*(1 if up else -1)-cost)/risk,t=x["t"]+300)
                    return None
                outcomes={str(r):outcome(entry+(1 if up else -1)*(r*risk+cost)) for r in (1,2,3) if r<=rr}
                consumed.update(keys)
                rows.append(dict(at=at,entry=entry,stop=stop,target=target,session=("Asia" if datetime.fromtimestamp(at,timezone.utc).hour<8 else "London" if datetime.fromtimestamp(at,timezone.utc).hour<13 else "NY" if datetime.fromtimestamp(at,timezone.utc).hour<21 else "Late"),tf=tf,direction=d,models=models,poi=sorted(set(tags)),rr=rr,band=band,actual=outcome(target),fixed=outcomes,trend=trend_relation(d,trend(hframes["4h"])),flow=confluence(dict.fromkeys(("spot_cvd","futures_cvd","delta","oi","volume","book","funding","basis","liquidations")),at),sample="in_sample" if at<=split else "holdout"))
    def portfolio(items,key="actual"):
        balance=peak=1000.; busy=0; wins=losses=skipped=unresolved=0; rs=[]; dd=0
        for e in sorted(items,key=lambda e:(e["at"],e["tf"]!="15m",e["direction"])):
            if e["at"]<=busy:skipped+=1;continue
            o=e["actual"] if key=="actual" else e["fixed"].get(key)
            if o is None:unresolved+=1;busy=START+243*86400 if e["sample"]=="in_sample" else END;continue
            busy=o["t"];r=o["r"];rs.append(r);balance*=1+min(.01,5*(abs(e["entry"]-e["stop"])+e["entry"]*.0014)/e["entry"])*r;peak=max(peak,balance);dd=max(dd,1-balance/peak);wins+=r>0;losses+=r<0
        return dict(trades=len(rs),wins=wins,losses=losses,win_rate=wins/len(rs) if rs else None,pnl=balance-1000,drawdown=dd,expectancy=sum(rs)/len(rs) if rs else None,skipped=skipped,unresolved=unresolved)
    groups=defaultdict(list)
    for e in rows:
        for k in (["combined",e["tf"],e["band"],e["trend"],e["sample"],e["session"]]+e["models"]+e["poi"] if e["tf"]=="15m" else ["5m"]):groups[k].append(e)
    out=dict(classification="partial_v5_2_strong_context_same_period",rejected=dict(rejected),missing=["W1/MN1 POI","other external K-levels","historical order flow","confirmed correction completion","next-open execution and funding"],start=START,end=END,candidates=len(rows),groups={k:portfolio(v) for k,v in groups.items()},fixed={str(r):portfolio([e for e in rows if e["tf"]=="15m" and str(r) in e["fixed"]],str(r)) for r in (1,2,3)},entries=rows)
    Path("data/BTC-okx-structural-replay-v5.json").write_text(json.dumps(out,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!="entries"}),flush=True)
if __name__=="__main__":run()
