"""Daily inside-bar deviation research: closed bars, context, M15 shift, range target.
Conservative market variant only; limit/FTA variants not yet wired.
"""
from research.baseline import replay as b
from research.runner.confirmed_filters import deviation_confirmed, entry_allowed, protection_trigger

MODEL="IB_M15_market"
def run(data,funding,expected_count,*,start,end,fee,slip):
    frames={tf:b.Frame(tf) for tf in b.FRAMES}
    book=b.Book(MODEL,fee,slip)
    daily=None; bounds=None; excursion={}; count=0
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
        if not eligible or not bounds: continue
        lo,hi=bounds
        # FTA management only after confirmed opposing shift; no raw touch protection.
        if book.pos:
            p=book.pos; d=p['d']
            for tf in (900,3600,14400):
                if events.get(900)!=-d: continue
                z=next((z for z in frames[tf].zones if z.side==-d and b.overlap(bar,z)),None)
                if z and protection_trigger(d,1,True,-d,900,True):
                    be=p['entry']
                    if d*(be-p['stop'])>0 and d*(bar.c-be)>0:
                        p['stop']=be
                        p.setdefault('management',[]).append({'time':b.utc(now),'reason':'FTA_M15_BE','tf':tf})
                    break
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
