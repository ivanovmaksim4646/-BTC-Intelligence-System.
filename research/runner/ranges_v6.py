"""Closed-bar H4/D1/W1 inside-bar and general range deviation candidates."""
from research.baseline import replay as b
from research.runner.execution_v6 import ExecutionBook
from research.runner.confirmed_filters import deviation_confirmed
from research.runner.structure_v7 import fta_ready

SPECS={"IB_H4":14400,"IB_D1":86400,"IB_W1":604800,"RANGE_H4":14400}
WEEK=604800
class Weekly(b.Frame):
    def feed(self,x):
        # UTC Monday boundary, independent of Unix epoch Thursday.
        shifted=x._replace(t=x.t+3*86400)
        closed=super().feed(shifted)
        return closed._replace(t=closed.t-3*86400) if closed else None

def range_bounds(bars):
    # Research proxy: six closed H4 bars, two touches at each edge, no trend assumption.
    if len(bars)<6:return None
    bars=list(bars)[-6:]
    lo=min(x.l for x in bars);hi=max(x.h for x in bars)
    if hi<=lo:return None
    tol=(hi-lo)*.15
    if sum(x.l<=lo+tol for x in bars)<2 or sum(x.h>=hi-tol for x in bars)<2:return None
    return lo,hi

def run(data,funding,expected_count,*,start,end,fee,slip,policy="structural"):
    frames={tf:b.Frame(tf) for tf in b.FRAMES}
    frames[WEEK]=Weekly(WEEK)
    books={n:ExecutionBook(n,fee,slip,policy) for n in SPECS}
    state={n:{"bounds":None,"previous":None,"exc":{}} for n in SPECS}
    count=0
    for bar in data:
        now=bar.t+300;eligible=start<=bar.t<end
        if eligible:count+=1
        for n,book in books.items():
            book.execute(bar,end,funding)
            st=state[n];bounds=st["bounds"]
            if not bounds:continue
            lo,hi=bounds
            for d in (1,-1):
                extreme=bar.l if d==1 else bar.h
                if (extreme<lo if d==1 else extreme>hi):
                    e=st["exc"].get(d)
                    if e is None or d*(extreme-e[0])<0:
                        st["exc"][d]=(extreme,e[1] if e else None)
                if d in st["exc"]:
                    hit=next(((tf,z) for tf in (WEEK,86400,14400,3600) for z in reversed(frames[tf].zones)
                              if z.side==d and b.overlap(bar,z) and d*(bar.c-bar.o)>0),None)
                    if hit:st["exc"][d]=(st["exc"][d][0],hit)
        events={};closed_bars={}
        for tf,f in frames.items():
            closed=f.feed(bar)
            if closed is None:continue
            # First weekly candle is partial unless it began Monday.
            if tf==WEEK and closed.t<data[0].t:continue
            _,ev,_=f.close(closed,now)
            closed_bars[tf]=closed
            if ev:events[tf]=ev
        if eligible:
            for n,book in books.items():
                book.after_close(bar,frames,events)
                st=state[n];bounds=st["bounds"]
                if not bounds or not book.idle():continue
                lo,hi=bounds
                s=book.setup
                if s:
                    if s.z not in frames[s.tf].zones or now-s.time>10800 or not b.through(s.d,b.signprice(s.d,bar),s.stop):
                        book.reject(now,"deviation_setup_invalid",s);book.setup=None
                        continue
                    if not fta_ready(s,frames,bar,now):continue
                    if now<=s.time or not (bar.l<=s.hi and bar.h>=s.lo and s.d*(bar.c-bar.o)>0):continue
                    target=b.Level(s.d,hi if s.d==1 else lo,"opposite_range_boundary")
                    book.setup=None
                else:
                    d=events.get(900)
                    e=st["exc"].get(d)
                    if not e or not e[1]:continue
                    extreme,(tf,z)=e
                    if z not in frames[tf].zones or not deviation_confirmed(d,lo,hi,extreme,bar.c,d,True):continue
                    s=b.Setup(d,z,tf,now,extreme-d*.1,bar.c,bar.c)
                    s.evidence=dict(range_low=lo,range_high=hi,deviation_extreme=extreme,
                         shift=b.shift_trace(frames[900],900),reentry_close=bar.c,poi_born_utc=b.utc(z.born))
                    target=b.Level(d,hi if d==1 else lo,"opposite_range_boundary")
                    st["exc"].pop(d,None)
                    if not fta_ready(s,frames,bar,now):
                        book.setup=s
                        continue
                rr,_=book.rr(s.d,bar.c,s.stop,target.px,market=True)
                if rr>=2:book.order=(s,target)
                else:
                    z=next(((tf,z) for tf in (900,3600) for z in reversed(frames[tf].zones)
                       if z.side==s.d and z.kind in ("OB","FVG","IFVG","Rejection")
                       and lo<=(z.hi if s.d==1 else z.lo)<=hi
                       and s.d*(bar.c-(z.hi if s.d==1 else z.lo))>0
                       and book.rr(s.d,z.hi if s.d==1 else z.lo,s.stop,target.px)[0]>=2),None)
                    if not z or not book.place_limit(s,target,z[1],z[0],now):book.reject(now,"no_valid_range_entry",s)
        # Range revisions become available only after the current bar is processed.
        for n,tf in SPECS.items():
            if tf not in closed_bars:continue
            st=state[n];c=closed_bars[tf];prev=st["previous"];bounds=st["bounds"]
            if bounds and not bounds[0]<=c.c<=bounds[1]:
                st["bounds"]=None;st["exc"]={};books[n].setup=None
                if books[n].pending:books[n].cancel(now,"range_expired")
            new=range_bounds(frames[tf].bars) if n.startswith("RANGE") and st["bounds"] is None else None
            if n.startswith("IB") and prev and c.h<prev.h and c.l>prev.l:new=(c.l,c.h)
            if new and new!=st["bounds"]:
                st["bounds"]=new;st["exc"]={};books[n].setup=None
                if books[n].pending:books[n].cancel(now,"range_replaced")
            st["previous"]=c
    if count!=expected_count:raise ValueError("Incomplete deviation evaluation coverage")
    return books
