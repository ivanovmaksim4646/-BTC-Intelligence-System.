"""Conservative structural paper risk planning; no execution or fabricated RR targets."""
from math import isfinite

def plan(direction, entry, head, zones, liquidity, *, cost_bps=14, buffer_bps=3, separate_fta=False):
    """Inputs are pre-entry confirmed zones and unswept liquidity only.
    Zone schema: low, high, direction, kind (FVG/IFVG/OB), confirmed_at.
    Caller must validate chronology and active status. Nearest opposing
    zone or liquidity is the first trouble area. With separate_fta, final TP
    is nearest verified liquidity; the FTA is preserved for management.
    """
    if direction not in ("long","short") or not all(type(x) in (int,float) and isfinite(x) and x>0 for x in (entry,head)):
        return {"status":"withheld","reason":"invalid_geometry"}
    long=direction=="long"
    if not (head<entry if long else head>entry):
        return {"status":"withheld","reason":"invalid_head"}
    anchors=[head]
    targets=[]
    for z in zones:
        lo,hi=z["low"],z["high"]
        if z["direction"]==direction and (lo<entry if long else hi>entry):
            # Only zones intersecting the original QM invalidation path.
            if lo<=head<=hi or (head<=lo<entry if long else entry<hi<=head):
                anchors.append(lo if long else hi)
        elif z["direction"]!=direction:
            edge=lo if long else hi
            if lo<=entry<=hi:
                return {"status":"withheld","reason":"entry_inside_opposing_poi"}
            if edge>entry if long else edge<entry:
                targets.append((edge,"opposing_"+z["kind"]))
    for level in liquidity:
        if level>entry if long else level<entry:
            targets.append((level,"unswept_liquidity"))
        elif min(anchors)<=level<entry if long else entry<level<=max(anchors):
            anchors.append(level)
    if not targets:
        return {"status":"withheld","reason":"no_verified_target"}
    stop=(min(anchors) if long else max(anchors))*(1-buffer_bps/10000 if long else 1+buffer_bps/10000)
    fta,fta_kind=min(targets,key=lambda x:abs(x[0]-entry))
    tp,kind=fta,fta_kind
    if separate_fta:
        # TP is the nearest independently verified profit-side liquidity.
        # Opposing imbalances are FTA, not arbitrarily selected final targets.
        final=[x for x in targets if x[1]=="unswept_liquidity"]
        if not final:
            return {"status":"withheld","reason":"no_verified_final_liquidity","fta":fta,"fta_kind":fta_kind}
        tp,kind=min(final,key=lambda x:abs(x[0]-entry))
    fta_zone=None
    if separate_fta and fta_kind.startswith("opposing_"):
        match=next((z for z in zones if z["direction"]!=direction and "opposing_"+z["kind"]==fta_kind and (z["low"] if long else z["high"])==fta),None)
        if match is not None:fta_zone={"low":match["low"],"high":match["high"],"kind":match["kind"]}
    risk=abs(entry-stop)+entry*cost_bps/10000
    reward=abs(tp-entry)-entry*cost_bps/10000
    net=reward/risk
    return {"status":"paper_candidate" if net>=2 else "withheld",
            "reason":"net_rr_pass" if net>=2 else "net_rr_below_two",
            "entry":entry,"stop_loss":stop,"take_profit":tp,"target_kind":kind,
            "rr_net_estimate":net,"cost_bps":cost_bps,"trade_signal":None,
            **({"fta":fta,"fta_kind":fta_kind,"fta_zone":fta_zone,"management":"fta_or_ltf_shift_be_v1"} if separate_fta else {})}
