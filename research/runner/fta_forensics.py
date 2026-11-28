"""Read-only forensic audit of exact v3 rejected setups, not a strategy retune."""
import json
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from research.baseline import replay as b
from research.baseline.dataset import START, END
from research.runner.inputs import verified_bars

SOURCE=Path("research/risk-results/structural-audit.json")
OUT=Path("research/fta-forensics")
def stamp(s):return int(datetime.fromisoformat(s).timestamp())
def zone_key(z,tf):return (z.kind,tf,z.lo,z.hi,z.born)
def key(d):return (d["kind"],d["tf"],d["low"],d["high"],stamp(d["formed_utc"]))
def info(s):
    return {k:v for k,v in s.items() if k not in ("in_contact",)}
def main():
    raw=json.loads(SOURCE.read_text())
    cases=[]
    for model,entries in raw.items():
        for x in entries:
            if "shift_inside_active_fta" not in x["events"]:continue
            idea=x["idea"]
            cases.append(dict(model=model,shift=idea["shift_time"],setup=stamp(x["at_utc"]),price=idea["shift_price"],entry=idea["entry_limit"],direction=idea["d"],zones=x["targets"]["shift_inside_zones"]))
    assert len(cases)==506
    watch=set(key(z) for c in cases for z in c["zones"])
    at=defaultdict(list)
    for i,c in enumerate(cases):at[c["shift"]].append(i)
    frames={tf:b.Frame(tf) for tf in b.FRAMES}
    stats={}
    bars,_=verified_bars(START,END,Path(".research-cache"))
    recent=deque(maxlen=144)
    sample_indices=set()
    by_model=defaultdict(list)
    for i,c in enumerate(cases):by_model[c["model"]].append(i)
    for group in by_model.values():
        for k in range(min(16,len(group))):sample_indices.add(group[k*(len(group)-1)//max(1,min(16,len(group))-1)])
    chart_cases={}
    active_charts={}
    for x in bars:
        now=x.t+300;recent.append(x)
        for i,record in list(active_charts.items()):
            if now<=cases[i]["shift"]+3600:record["bars"].append(list(x))
            else:active_charts.pop(i)
        for tf,f in frames.items():
            for z in f.zones:
                k=zone_key(z,tf)
                if k not in watch:continue
                s=stats.setdefault(k,dict(touches=0,contact_bars=0,full_fill=False,first_touch=None,last_touch=None,in_contact=False,far_edge_closes_m5=0))
                contact=b.overlap(x,z)
                if contact:
                    if not s["in_contact"]:s["touches"]+=1
                    s["contact_bars"]+=1
                    if s["first_touch"] is None:s["first_touch"]=b.utc(now)
                    s["last_touch"]=b.utc(now)
                s["in_contact"]=contact
                if x.l<=z.lo if z.side==1 else x.h>=z.hi:s["full_fill"]=True
                if b.through(-z.side,x.c,z.lo if z.side==1 else z.hi):s["far_edge_closes_m5"]+=1
        for tf,f in frames.items():
            bar=f.feed(x)
            if bar is not None:f.close(bar,now)
        if now not in at:continue
        for i in at[now]:
            c=cases[i];records=[]
            for z in c["zones"]:
                k=key(z);state=stats.get(k)
                present=any(zone_key(v,z["tf"])==k for v in frames[z["tf"]].zones)
                # Touch stats through the shift close; exclude current episode
                # from prior episode count if contact remains active.
                prev=max(0,state["touches"]-int(state["in_contact"])) if state else 0
                records.append({**z,"present_at_shift_close":present,"prior_completed_touch_episodes":prev,"state_through_shift":info(state) if state else None,"age_days":(now-k[-1])/86400})
            c["zone_history"]=records
            if i in sample_indices:
                chart_cases[i]={"case":c,"bars":[list(v) for v in recent]}
                active_charts[i]=chart_cases[i]
    counts=Counter()
    for c in cases:
        zs=c.get("zone_history",[])
        if not zs:raise ValueError("Missing shift snapshot")
        counts["cases"]+=1
        if any(z["prior_completed_touch_episodes"]>=1 for z in zs):counts["any_previously_tested"]+=1
        if all(z["prior_completed_touch_episodes"]>=1 for z in zs):counts["all_previously_tested"]+=1
        if any(z["prior_completed_touch_episodes"]>=2 for z in zs):counts["any_two_prior_tests"]+=1
        if all(z["prior_completed_touch_episodes"]>=2 for z in zs):counts["all_two_prior_tests"]+=1
        if any(z["state_through_shift"] and z["state_through_shift"]["full_fill"] for z in zs):counts["any_wick_far_edge"]+=1
        if all(z["state_through_shift"] and z["state_through_shift"]["full_fill"] for z in zs):counts["all_wick_far_edge"]+=1
        if any(not z["present_at_shift_close"] for z in zs):counts["any_not_active_at_shift"]+=1
        if all(not z["present_at_shift_close"] for z in zs):counts["all_not_active_at_shift"]+=1
        for z in zs:
            counts["zone_instances"]+=1
            if z["prior_completed_touch_episodes"]>=1:counts["zone_instances_pretested"]+=1
            if z["prior_completed_touch_episodes"]>=2:counts["zone_instances_two_tests"]+=1
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"summary.json").write_text(json.dumps(dict(classification="diagnostic_only",counts=dict(counts),sample_size=len(chart_cases),definitions={"prior_test":"Completed distinct M5 overlap episode before the shift close; not a discretionary validity verdict","far_edge":"Wick reached opposite zone edge; only automatically invalidates FVG/IFVG in v3","present":"Same exact zone present in its own timeframe state at shift close"}),indent=2)+"\n")
    (OUT/"cases.json").write_text(json.dumps(cases,separators=(",",":"))+"\n")
    # Compact browser-readable candle evidence, one chart per sampled case.
    from html import escape
    parts=["<!doctype html><meta charset=utf-8><title>FTA audit charts</title><style>body{font:15px system-ui;max-width:1000px;margin:auto}section{margin:24px 0}svg{width:100%;height:auto;background:#fafafa}</style><h1>FTA rejection sample</h1><p>48 systematic samples across models; M5 candles, shift marker, entry and opposing zones. Visual review required.</p>"]
    for i,r in chart_cases.items():
        c=r["case"];xs=r["bars"];zones=c["zone_history"]
        lo=min([v[3] for v in xs]+[z["low"] for z in zones]+[c["entry"]]);hi=max([v[2] for v in xs]+[z["high"] for z in zones]+[c["entry"]])
        def yy(p):return 10+(hi-p)/max(1,hi-lo)*300
        w=900/len(xs)
        elements=[]
        for z in zones:
            y=yy(z["high"]);height=max(1,yy(z["low"])-y)
            elements.append(f'<rect x="0" y="{y:.2f}" width="900" height="{height:.2f}" fill="#b86d29" opacity=".12"><title>{escape(str(z))}</title></rect>')
        for k,v in enumerate(xs):
            t,o,h,l,cl,*_=v;xx=(k+.5)*w;color="#178061" if cl>=o else "#be4242"
            elements.append(f'<path d="M{xx:.2f},{yy(h):.2f} V{yy(l):.2f}" stroke="{color}"/><rect x="{xx-w*.31:.2f}" y="{min(yy(o),yy(cl)):.2f}" width="{w*.62:.2f}" height="{max(1,abs(yy(o)-yy(cl))):.2f}" fill="{color}"/>')
            if t+300==c["shift"]:elements.append(f'<path d="M{xx:.2f},0 V320" stroke="#6048ad" stroke-dasharray="4 3"/>')
        elements.append(f'<path d="M0,{yy(c["entry"]):.2f} H900" stroke="#16447f" stroke-dasharray="5 3"/>')
        parts.append(f'<section><h2>{escape(c["model"])} | {b.utc(c["shift"])} | {"LONG" if c["direction"]==1 else "SHORT"}</h2><p>Shift {c["price"]}; Entry {c["entry"]}; violet = shift close; blue = entry.</p><svg viewBox="0 0 900 320">{"".join(elements)}</svg><pre>{escape(json.dumps(zones,indent=2))}</pre></section>')
    (OUT/"charts.html").write_text("".join(parts))
    print("FTA_FORENSICS",json.dumps(dict(counts),sort_keys=True))
if __name__=="__main__":main()
