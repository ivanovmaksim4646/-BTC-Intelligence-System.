"""Closed M15 QM neckline shift, independent of same-bar TV webhooks.
Conservative research/live candidate route; no execution. M5 used only for retest.
OB definition matches baseline research: last opposite candle before a close
beyond the preceding three candles' extreme. Not discretionary OB validation.
"""
import datetime as dt
from src.okx_market_context_v1 import validate_frame
from src.okx_entry_evidence_gate_v1 import fresh, prior_poi_zones, structural_plan, VENUE
from src.okx_structural_risk_v3 import plan

M15=900
M5=300
LOOKBACK=3*3600

def qm_shifts(bars):
    """First close through neckline after a confirmed swept shoulder/head.
    Two right bars must have closed before the shift; no future pivot at break.
    """
    pivots=[]
    used=set()
    out=[]
    for i,b in enumerate(bars):
        k=i-3
        if k>=2:
            p=bars[k]
            peers=bars[k-2:k]+bars[k+1:k+3]
            hi=all(p["h"]>x["h"] for x in peers)
            lo=all(p["l"]<x["l"] for x in peers)
            if hi!=lo:
                d="H" if hi else "L"
                v=p["h"] if hi else p["l"]
                item=(d,v,p["t"])
                if pivots and pivots[-1][0]==d:
                    if (v>pivots[-1][1] if hi else v<pivots[-1][1]):
                        pivots[-1]=item
                else:pivots.append(item)
        if i==0:continue
        # The last confirmed pivot need not be the head: internal pivots can
        # occur between the sweep and neckline break. Scan recent triples.
        for a,n,h in reversed(list(zip(pivots,pivots[1:],pivots[2:]))[-12:]):
            short=(a[0],n[0],h[0])==("H","L","H") and h[1]>a[1]
            long=(a[0],n[0],h[0])==("L","H","L") and h[1]<a[1]
            if not (short or long):continue
            direction="short" if short else "long"
            key=(direction,h[2],n[2])
            if key in used:continue
            if b["t"]-h[2]>12*3600:continue
            since=[x for x in bars[:i] if x["t"]>h[2]]
            if any((x["h"]>h[1] if short else x["l"]<h[1]) for x in since+[b]):continue
            # Earlier closes through the neckline invalidate a delayed signal.
            if any((x["c"]<n[1] if short else x["c"]>n[1]) for x in since):continue
            if not (bars[i-1]["c"]>=n[1]>b["c"] if short else bars[i-1]["c"]<=n[1]<b["c"]):continue
            used.add(key)
            out.append({"direction":direction,"shoulder":a[1],"neckline":n[1],"head":h[1],
                        "head_open":h[2],"shift_close":b["t"]+M15})
            break
    return out

def ob_zones(bars,step,at,direction):
    short=direction=="short"
    prior=[b for b in bars if b["t"]+step<=at]
    result=[]
    for i in range(3,len(prior)):
        b,a=prior[i],prior[i-1]
        opp=a["c"]>a["o"] if short else a["c"]<a["o"]
        edge=min(x["l"] for x in prior[i-3:i]) if short else max(x["h"] for x in prior[i-3:i])
        if not opp or not (b["c"]<edge if short else b["c"]>edge):continue
        if any((x["c"]>a["h"] if short else x["c"]<a["l"]) for x in prior[i+1:]):continue
        result.append({"direction":direction,"kind":"OB","low":a["l"],"high":a["h"],
                       "formed":a["t"],"available_at":b["t"]+step})
    return result

def evaluate(snapshot,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    out={"status":"unavailable","reasons":[],"shifts":[],"structural_research":[]}
    def fail(reason):
        out["reasons"].append(reason)
        return out
    if not isinstance(snapshot,dict) or snapshot.get("source")!=VENUE or snapshot.get("status")!="verified" or not fresh(snapshot.get("collected_at_utc"),now):
        return fail("stale_or_wrong_venue")
    raw=snapshot.get("timeframes") or {}
    frames={}
    for tf,step in (("5m",300),("15m",900),("1h",3600),("4h",14400)):
        bars=validate_frame(raw.get(tf),step,now)
        if bars is None:return fail("invalid_"+tf)
        frames[tf]={"bars":bars}
    m5=frames["5m"]["bars"]
    close=m5[-1]["t"]+M5
    if not 0<=now.timestamp()-close<=360:return fail("stale_m5")
    for tf,step in (("15m",900),("1h",3600),("4h",14400)):
        if not 0<=close-frames[tf]["bars"][-1]["t"]-step<step:return fail("unaligned_"+tf)
    out["status"]="observed"
    for q in qm_shifts(frames["15m"]["bars"]):
        shift=q["shift_close"]
        if not 0<=close-shift<=LOOKBACK:continue
        short=q["direction"]=="short"
        direction=q["direction"]
        row={**q,"status":"shift_observed","reasons":[]}
        out["shifts"].append(row)
        head=q["head_open"]
        subsequent=[b for b in m5 if shift<=b["t"]]
        if any((b["h"]>=q["head"] if short else b["l"]<=q["head"]) for b in subsequent):
            row["reasons"].append("head_invalidated");continue
        # The POI must exist before the head and be touched by the head candle.
        headbar=next(b for b in frames["15m"]["bars"] if b["t"]==head)
        hits=[]
        for tf,step in (("1h",3600),("4h",14400)):
            ht=frames[tf]["bars"]
            for z in prior_poi_zones(ht,step,head,direction)+ob_zones(ht,step,head,direction):
                if not headbar["l"]<=z["high"] or not headbar["h"]>=z["low"]:continue
                if any((b["c"]>z["high"] if short else b["c"]<z["low"]) for b in frames["15m"]["bars"] if head<=b["t"]):continue
                hits.append((tf,z))
        if not hits:row["reasons"].append("no_active_pre_head_mtf_poi");continue
        row["poi_matches"]=[{"htf":tf,**z} for tf,z in hits]
        # M5 confirmation is only a subsequent retest of the M15 neckline,
        # not a second M5 shift. No same-bar TradingView event required.
        level=q["neckline"]
        first=next((b for b in subsequent if b["l"]<=level<=b["h"] and (b["c"]<level if short else b["c"]>level)),None)
        if first is None:row["status"]="watch_retest";continue
        row["retest_close"]=first["t"]+M5
        if first["t"]+M5!=close:
            row["reasons"].append("first_retest_already_passed");continue
        for tf,z in hits:
            risk=structural_plan(frames,direction,first["c"],q["head"],z,close)
            p={"direction":direction,"entry_close_utc":close,"htf":tf,
               "poi_kind":z["kind"],"poi_formed":z["formed"],"model":"MTF_POI_QM_M15",
               "shift_close_utc":shift,"neckline":level,"qm_head":head,
               "episode_id":f"{direction}:{head}:{shift}",**risk}
            out["structural_research"].append(p)
        row["status"]="retest_observed"
    if not out["shifts"]:out["reasons"].append("no_recent_m15_qm_shift")
    return out
