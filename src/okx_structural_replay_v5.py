"""Exploratory v5 subset: causal candle replay, no historical order-flow claims."""
import json
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
    steps={"5m":300,"15m":900,"1h":3600,"4h":14400}
    closes={tf:[x["t"]+steps[tf] for x in b] for tf,b in frames.items()}
    m5=frames["5m"]
    rows=[]
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
            for k in ("1h","4h"):
                j=bisect_right(closes[k],b["t"])
                hframes[k]=frames[k][max(0,j-120):j]
            for d in ("long","short"):
                up=d=="long"; events=[]; tags=[]; levels=[]
                for k,h in hframes.items():
                    for z in prior_poi_zones(h,steps[k],b["t"],d):
                        touch=[x for x in p[-12:] if x["t"]>=z["available_at"] and x["l"]<=z["high"] and x["h"]>=z["low"]]
                        if touch and not any((x["c"]<z["low"] if up else x["c"]>z["high"]) for x in window if x["t"]>=touch[0]["t"]):
                            events.append(dict(direction=d,kind="POI",tf=k,known_at=touch[-1]["t"]+step,valid=True))
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
                            events.append(dict(direction=d,kind="internal_sweep",known_at=x["t"]+step,valid=True))
                shift=bool(s and s["kind"].startswith("bullish" if up else "bearish") and contextual_shift(d,b,p,s["break_level"],events))
                models=[]
                if shift:models.append("context_shift")
                qmatches=[q for q in qm if q["direction"]==d]
                if qmatches and tags:models.append("MTF_POI_QM")
                if dev==d and events:models.append("inside_deviation")
                if not models or not levels:continue
                entry=b["c"]; stop=(min(x["l"] for x in window[-12:])*.9997 if up else max(x["h"] for x in window[-12:])*1.0003)
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
                        if sl or hit:return dict(r=-1 if sl else (abs(tp-entry)-cost)/risk,t=x["t"]+300)
                    return None
                outcomes={str(r):outcome(entry+(1 if up else -1)*(r*risk+cost)) for r in (1,2,3) if r<=rr}
                rows.append(dict(at=at,tf=tf,direction=d,models=models,poi=sorted(set(tags)),rr=rr,band=band,actual=outcome(target),fixed=outcomes,trend=trend_relation(d,trend(hframes["4h"])),flow=confluence(dict.fromkeys(("spot_cvd","futures_cvd","delta","oi","volume","book","funding","basis","liquidations")),at),sample="in_sample" if at<=split else "holdout"))
    def portfolio(items,key="actual"):
        balance=peak=1000.; busy=0; wins=losses=skipped=unresolved=0; rs=[]; dd=0
        for e in sorted(items,key=lambda e:(e["at"],e["tf"]!="15m",e["direction"])):
            if e["at"]<=busy:skipped+=1;continue
            o=e["actual"] if key=="actual" else e["fixed"].get(key)
            if o is None:unresolved+=1;busy=START+243*86400 if e["sample"]=="in_sample" else END;continue
            busy=o["t"];r=o["r"];rs.append(r);balance*=1+.01*r;peak=max(peak,balance);dd=max(dd,1-balance/peak);wins+=r>0;losses+=r<0
        return dict(trades=len(rs),wins=wins,losses=losses,win_rate=wins/len(rs) if rs else None,pnl=balance-1000,drawdown=dd,expectancy=sum(rs)/len(rs) if rs else None,skipped=skipped,unresolved=unresolved)
    groups=defaultdict(list)
    for e in rows:
        for k in ["combined",e["tf"],e["band"],e["trend"],e["sample"]]+e["models"]+e["poi"]:groups[k].append(e)
    out=dict(classification="partial_v5_exploratory_same_period",missing=["D1/W1/MN1 POI","external sweep and K-level","historical order flow","confirmed correction completion","session comparisons"],start=START,end=END,candidates=len(rows),groups={k:portfolio(v) for k,v in groups.items()},fixed={str(r):portfolio([e for e in rows if str(r) in e["fixed"]],str(r)) for r in (1,2,3)},entries=rows)
    Path("data/BTC-okx-structural-replay-v5.json").write_text(json.dumps(out,indent=2))
    print(json.dumps({k:v for k,v in out.items() if k!="entries"}),flush=True)
if __name__=="__main__":run()
