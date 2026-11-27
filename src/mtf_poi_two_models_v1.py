"""Independent causal MTF POI research; no live orders or admission."""
from src.okx_entry_evidence_gate_v1 import prior_poi_zones
from src.strategy_models_v1 import scan_qm
from src.okx_market_context_v1 import fresh_structure_break
from src.okx_outcome_tracker_v1 import check_bar
STEPS={"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}

def zones(bars, step, at, direction):
    prior=[b for b in bars if b["t"]+step<=at]
    result=prior_poi_zones(prior,step,at,direction)
    # Research proxy: last opposite candle before displacement through prior range.
    # This is not a verified discretionary order block.
    for i in range(3,len(prior)):
        a,b=prior[i-1],prior[i]
        short=direction=="short"
        opposite=a["c"]>a["o"] if short else a["c"]<a["o"]
        displaced=b["c"]<min(x["l"] for x in prior[i-3:i]) if short else b["c"]>max(x["h"] for x in prior[i-3:i])
        if opposite and displaced:
            z={"kind":"OB_PROXY","low":a["l"],"high":a["h"],"available_at":b["t"]+step}
            if not any((x["c"]>z["high"] if short else x["c"]<z["low"]) for x in prior[i+1:]):
                result.append(z)
    return result

def evaluate(frames,at,ltf="15m"):
    """Detect research WATCH only, using closed bars and pre-existing zones."""
    closed={tf:[b for b in bars if b["t"]+STEPS[tf]<=at] for tf,bars in frames.items() if tf in STEPS}
    bars=closed.get(ltf,[])
    if len(bars)<30 or not all(check_bar(b) for b in bars):
        return []
    if any(b["t"]-a["t"]!=STEPS[ltf] for a,b in zip(bars,bars[1:])):
        return []
    event=fresh_structure_break(bars,ltf)
    if not event:return []
    direction="short" if event["kind"].startswith("bearish") else "long" if event["kind"].startswith("bullish") else None
    if not direction:return []
    out=[]
    for tf in ("1d","4h","1h","15m"):
        if STEPS[tf]<=STEPS[ltf]:continue
        for z in zones(closed.get(tf,[]),STEPS[tf],at-STEPS[ltf],direction):
            touches=[b for b in bars[-12:] if b["t"]>=z["available_at"] and b["l"]<=z["high"] and b["h"]>=z["low"]]
            if not touches:continue
            touch=touches[-1]["t"]
            if any((b["c"]>z["high"] if direction=="short" else b["c"]<z["low"]) for b in bars if b["t"]>=touch):continue
            qm=any(q["direction"]==direction and q["head_time"]>=touch for q in scan_qm(bars))
            model="MTF_POI_QM_M15" if qm and ltf=="15m" else None
            if model:out.append({"model":model,"direction":direction,"poi_tf":tf,"poi":z,"close":at,"status":"WATCH_RESEARCH"})
            # Continuation requires prior displacement; retest is not yet verified.
            if tf in ("1h","4h","15m") and len(bars)>=12:
                prior=bars[-12:-3]
                if (prior[-1]["c"]<prior[0]["o"] if direction=="short" else prior[-1]["c"]>prior[0]["o"]):
                    out.append({"model":"MTF_POI_CONTINUATION","direction":direction,"poi_tf":tf,"poi":z,"close":at,"status":"WATCH_RESEARCH","retest_verified":False})
    return out
