"""Daily inside-bar deviation research: closed bars, context, M15 shift, range target.
Market entry with confirmed FTA protection; limit and general range not yet wired.
"""
from datetime import datetime
from research.baseline import replay as b
from research.runner.confirmed_filters import deviation_confirmed, entry_allowed, protection_trigger, tighten_stop

MODEL="IB_M15_market"
def run(data,funding,expected_count,*,start,end,fee,slip):
    frames={tf:b.Frame(tf) for tf in b.FRAMES}
    book=b.Book(MODEL,fee,slip)
    daily=None; bounds=None; excursion={}; count=0; fta_touch=None; tracked_entry=None
    for bar in data:
        now=bar.t+300
        eligible=start<=bar.t<end
        if eligible: count+=1
        book.execute(bar,end,funding)
        if bounds:
            lo,hi=bounds
            for d in (1,-1):
                extreme=bar.l if d==1 else bar.h
                if (extreme<lo if d==1 else extreme>hi):
                    e=excursion.get(d)
                    if e is None or d*(extreme-e[0])<0:
                        excursion[d]=(extreme,e[1] if e else None)
                if d in excursion:
                    hit=next(((tf,z) for tf in (86400,14400,3600) for z in reversed(frames[tf].zones)
                              if z.side==d and b.overlap(bar,z) and d*(bar.c-bar.o)>0),None)
                    if hit: excursion[d]=(excursion[d][0],hit)
        events={}
        for tf,f in frames.items():
            closed=f.feed(bar)
            if closed is None: continue
            _,ev,_=f.close(closed,now)
            if ev: events[tf]=ev
            if tf==86400:
                if daily and closed.h<daily.h and closed.l>daily.l:
                    bounds=(closed.l,closed.h);excursion={}
                elif bounds and (closed.c<bounds[0] or closed.c>bounds[1]):
                    bounds=None;excursion={}
                daily=closed
        if not eligible: continue
        # Remember opposing zones touched after entry, even if range expires.
        # Only a subsequent closed opposing shift can tighten the stop.
        if book.pos:
            p=book.pos; d=p['d']
            p.setdefault('initial_stop',p['stop'])
            risk=abs(p['entry']-p['initial_stop'])
            active=[(tf,z) for tf in (14400,3600,900) for z in frames[tf].zones
                    if z.side==-d and z.born<=bar.t]
            if tracked_entry!=p['entry_utc']:
                tracked_entry=p['entry_utc']; fta_touch=None
            if fta_touch and fta_touch not in active:
                fta_touch=None
            hit=next(((tf,z) for tf,z in active if b.overlap(bar,z)),None)
            if hit:
                fta_touch=hit
            hit=fta_touch
            if hit and risk>0:
                tf,z=hit
                edge=z.lo if d==1 else z.hi
                distance=max(0,d*(edge-p['entry'])/risk)
                shift_tf=next((step for step in (900,300)
                    if protection_trigger(d,distance,True,events.get(step),step,step in events)),None)
                if shift_tf:
                    old=p['stop']
                    # Research convention: prefer the most protective confirmed
                    # structural pivot with an intact same-side FVG ahead of it.
                    # Otherwise use entry-price BE. Never loosen the stop.
                    candidates=[]
                    for anchor_tf in (3600,900):
                        frame=frames[anchor_tf]
                        pivot=frame.last.get(-d)
                        if not pivot: continue
                        if pivot.t < datetime.fromisoformat(p['entry_utc']).timestamp(): continue
                        anchor=pivot.px
                        if any(q.kind=='FVG' and q.side==d and q.born<=now
                               and d*((q.lo if d==1 else q.hi)-anchor)>0
                               and d*(bar.c-(q.hi if d==1 else q.lo))>=0
                               for q in frame.zones):
                            proposed=anchor-d*.1
                            if tighten_stop(d,old,proposed,bar.c)!=old:
                                candidates.append((proposed,anchor_tf))
                    proposed,anchor_tf=max(candidates,key=lambda x:d*x[0]) if candidates else (p['entry'],None)
                    new=tighten_stop(d,old,proposed,bar.c)
                    if new!=old:
                        p['stop']=new
                        p.setdefault('management',[]).append({'time':b.utc(now),'reason':'FTA_structural' if anchor_tf else 'FTA_BE','anchor_tf':anchor_tf,'tf':tf,
                            'shift_tf':shift_tf,'distance_r':distance,'old_stop':old,'new_stop':new})
                    fta_touch=None
        if not bounds: continue
        lo,hi=bounds
        if not book.idle() or 900 not in events: continue
        d=events[900]; e=excursion.get(d)
        if not e or not e[1]: continue
        extreme,(tf,z)=e
        if z not in frames[tf].zones: continue
        if not deviation_confirmed(d,lo,hi,extreme,bar.c,d,True): continue
        stop=extreme-d*.1; target=hi if d==1 else lo
        rr=d*(target-bar.c)/abs(bar.c-stop) if bar.c!=stop else 0
        # Conservative FTA gate: no entry inside an active opposing zone.
        inside=any(q.side==-d and q.lo<=bar.c<=q.hi for t in (900,3600,14400) for q in frames[t].zones)
        if not entry_allowed(True,True,rr,inside): continue
        s=b.Setup(d,z,tf,now,stop,bar.c,bar.c)
        s.evidence={'range_low':lo,'range_high':hi,'deviation_extreme':extreme,
                    'shift':b.shift_trace(frames[900],900),'reentry_close':bar.c,
                    'poi_born_utc':b.utc(z.born)}
        book.order=(s,b.Level(d,target,'opposite_IB_boundary'))
        excursion.pop(d,None)
    if count!=expected_count: raise ValueError('Incomplete evaluation coverage')
    return {MODEL:book}
