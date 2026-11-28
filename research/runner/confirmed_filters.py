"""User-confirmed entry/management predicates; research only, no execution."""
from dataclasses import dataclass

def deviation_confirmed(side, low, high, excursion, close, shift_side, shift_closed):
    if side not in (1,-1) or low >= high:
        return False
    return (excursion < low if side == 1 else excursion > high) and low < close < high and shift_side == side and shift_closed

def fvg_state(side, low, high, wick, close):
    if side == 1:
        return "invalidated" if close < low else "full_fill" if wick <= low else "partial" if wick < high else "untouched"
    return "invalidated" if close > high else "full_fill" if wick >= high else "partial" if wick > low else "untouched"

def deeper_retest(side, previous_extreme, current_extreme):
    return side * (current_extreme - previous_extreme) < 0

def limit_edge(side, low, high):
    return high if side == 1 else low

def protection_trigger(side, fta_distance_r, reaction, shift_side, shift_tf, confirmed):
    if not reaction or not confirmed or shift_side != -side:
        return False
    return shift_tf == 900 or (shift_tf == 300 and 0 <= fta_distance_r <= .5)

def continuation(side, prior_extreme, close):
    return side * (close - prior_extreme) > 0

def tighten_stop(side, old_stop, proposed_stop, current_price):
    return proposed_stop if side*(proposed_stop-old_stop)>0 and side*(current_price-proposed_stop)>0 else old_stop

def entry_allowed(context, confirmed_shift, rr, inside_fta=False, fta_invalidated=False, retest_after_invalidation=False):
    return bool(context and confirmed_shift and rr >= 2 and (not inside_fta or (fta_invalidated and retest_after_invalidation)))

def cancel_pending(side, target, favorable_extreme, opposite_shift_in_fta):
    return side*(favorable_extreme-target)>=0 or opposite_shift_in_fta

def self_test():
    assert deviation_confirmed(1,100,110,99,102,1,True)
    assert not deviation_confirmed(1,100,110,99,99,1,True)
    assert deviation_confirmed(-1,100,110,111,108,-1,True)
    assert not deviation_confirmed(-1,100,110,111,108,-1,False)
    assert fvg_state(1,100,110,99,101)=="full_fill"
    assert fvg_state(1,100,110,99,98)=="invalidated"
    assert fvg_state(-1,100,110,111,109)=="full_fill"
    assert deeper_retest(1,105,103) and not deeper_retest(1,103,105)
    assert limit_edge(1,100,110)==110 and limit_edge(-1,100,110)==100
    assert protection_trigger(1,.5,True,-1,300,True)
    assert not protection_trigger(1,.6,True,-1,300,True)
    assert not protection_trigger(1,.2,True,-1,900,False)
    assert protection_trigger(-1,2,True,1,900,True)
    assert continuation(1,100,101) and not continuation(1,100,100)
    assert tighten_stop(1,90,95,100)==95 and tighten_stop(1,95,90,100)==95
    assert not entry_allowed(True,True,3,True,True,False)
    assert entry_allowed(True,True,2,True,True,True)
    assert cancel_pending(1,110,110,False) and cancel_pending(-1,90,95,True)

if __name__=="__main__":
    self_test()
    print("Confirmed-rule predicate checks passed")
