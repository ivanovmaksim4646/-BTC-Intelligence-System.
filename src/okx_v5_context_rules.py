"""Causal context primitives for v5 research; not a live entry engine."""
from collections import Counter
from statistics import median
from math import isfinite

MTF=("1h","4h")
HTF=("1d","1w","1M")
LTF=("15m","5m")

def contextual_shift(direction, bar, previous, break_level, context_events):
    """Context must be known before or at the break; no airborne shifts.
    Displacement research threshold: body >= 1.5x median of prior 20 bodies,
    and body >= 60% of candle range. These are fixed exploratory assumptions.
    """
    if direction not in ("long","short") or len(previous)<20:
        return False
    if any(p["t"]>=bar["t"] for p in previous):
        return False
    body=abs(bar["c"]-bar["o"])
    span=bar["h"]-bar["l"]
    typical=median(abs(p["c"]-p["o"]) for p in previous[-20:])
    if span<=0 or typical<=0 or body<1.5*typical or body/span<.6:
        return False
    if direction=="long":
        broken=previous[-1]["c"]<=break_level<bar["c"] and bar["c"]>bar["o"]
    else:
        broken=previous[-1]["c"]>=break_level>bar["c"] and bar["c"]<bar["o"]
    return broken and any(e.get("direction")==direction
        and e.get("valid") is True and e.get("known_at",float("inf"))<=bar["t"]
        and (e.get("kind") in ("internal_sweep","external_sweep") or
             (e.get("kind") in ("POI","K_LEVEL") and e.get("tf") in MTF+HTF))
        for e in context_events)

def inside_deviation(mother,inside,probe):
    """Single-sided false break of mother range, closing back within it."""
    if not mother["t"]<inside["t"]<probe["t"]:
        return None
    if not (mother["l"]<=inside["l"]<=inside["h"]<=mother["h"]):
        return None
    if not mother["l"]<probe["c"]<mother["h"]:
        return None
    high=probe["h"]>mother["h"]
    low=probe["l"]<mother["l"]
    if high==low:
        return None
    return "short" if high else "long"

def rr_band(rr):
    if not isfinite(rr) or rr<1:return None
    return "1_to_2" if rr<2 else "2_to_3" if rr<3 else "3_plus"

def confluence(factors,at):
    """One observation per named factor. Unknown/stale not a neutral vote.
    Caller supplies independently validated direction and validity window.
    """
    result=Counter({"long":0,"short":0,"neutral":0,"missing":0})
    for factor in factors.values():
        if not isinstance(factor,dict) or factor.get("verified") is not True:
            result["missing"]+=1
            continue
        known=factor.get("known_at")
        until=factor.get("valid_until")
        side=factor.get("side")
        if not isinstance(known,(int,float)) or not isinstance(until,(int,float)) or not known<=at<=until or side not in ("long","short","neutral"):
            result["missing"]+=1
        else:result[side]+=1
    return dict(result)

def trend_relation(direction, state, correction_completed=False):
    if state not in ("bullish","bearish"):return "mixed_or_unknown"
    aligned=(direction=="long")== (state=="bullish")
    if not aligned:return "countertrend_correction_candidate"
    return "continuation_after_correction" if correction_completed else "aligned_unconfirmed_correction"
