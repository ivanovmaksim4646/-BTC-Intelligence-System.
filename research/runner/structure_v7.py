"""Backtest #7 candidate structure replay. Frozen #6 baseline is imported, never edited.
M15 closed shift required for OF; M5 candles still provide execution and retest observations.
Not yet a complete integrated strategy.
"""
from collections import deque
from research.runner.execution_v6 import ExecutionBook
from research.baseline.replay import utc
from research.baseline.replay import (Frame, Liquidity, Book, Setup, FRAMES, FEE, SLIP,
    stamp_start, stamp_end, through, overlap, signprice, trace, shift_trace, BASE_MODELS as OLD_MODELS)
MODELS=['QM_M15']+[f'OF_{tf}_{f}' for tf in ('M15','H1','H4') for f in ('base','weak')]
def backtest(data, funding, expected_count=365*288, *, models=None, start=None, end=None, fee=FEE, slip=SLIP):
 start=stamp_start if start is None else start
 end=stamp_end if end is None else end
 frames={step:Frame(step) for step in FRAMES}; liq=Liquidity()
 names=MODELS if models is None else models
 if not names or set(names)-set(MODELS) or len(names)!=len(set(names)):raise ValueError('invalid models')
 books={n:ExecutionBook(n,fee,slip) for n in names};touches={1:deque(),-1:deque()}
 count=0
 for b in data:
  now=b.t+300;eligible=start<=b.t<end
  if eligible:count+=1
  for book in books.values():book.execute(b,end,funding)
  liq.bar(b)
  # M5 reaction to a previously known HTF zone. Timestamp touch at bar open for comparing QM head.
  for d in (1,-1):
   q=touches[d]
   while q and b.t-q[0][0]>10800:q.popleft()
   choice=None
   for tf in (86400,14400,3600):
    for z in reversed(frames[tf].zones):
     if z.side==d and overlap(b,z) and through(d,b.c,(z.lo+z.hi)/2) and d*(b.c-b.o)>0:
      choice=(b.t,tf,z);break
    if choice:break
   if choice:q.append(choice)
  events={};qm=None
  for tf in FRAMES:
   f=frames[tf];bar=f.feed(b)
   if bar is None:continue
   pivot,ev,pattern=f.close(bar,now)
   if ev:events[tf]=ev
   if tf==900:qm=pattern
   if tf>=3600 and pivot:liq.levels.append(Level(pivot.side,pivot.px,'swing '+str(tf//3600)+'H'))
  if not eligible:continue
  m15=frames[900]
  for name,book in books.items():
   book.after_close(b,frames,events)
   if not book.idle():continue
   s=book.setup
   if s and (s.z not in frames[s.tf].zones or now-s.time>10800 or not through(s.d,signprice(s.d,b),s.stop)):
    reason='poi_invalidated' if s.z not in frames[s.tf].zones else 'expired' if now-s.time>10800 else 'stop_breached_before_entry'
    book.reject(now,reason,s);book.setup=None;s=None
   if s and now>s.time and b.l<=s.hi and b.h>=s.lo and through(s.d,b.c,(s.lo+s.hi)/2) and s.d*(b.c-b.o)>0:
    book.setup=None
    # Weakness of opposing aggressors: positive signed delta for the opponent,
    # but close back in the setup direction, in outer half of the M5 candle.
    delta=2*b.buy-b.v
    if name.endswith('weak') and not (b.v>0 and s.d*delta/b.v<=-.10 and s.d*(b.c-(b.h+b.l)/2)>0):
     book.reject(now,'weakness_filter',s);continue
    target=liq.target(s.d,b.c)
    if target:
     s.evidence['retest_close_utc']=utc(now)
     opposing=any(z.side==-s.d and z.lo<=b.c<=z.hi for tf in (900,3600,14400) for z in frames[tf].zones)
     if opposing:
      book.reject(now,'entry_inside_fta',s);continue
     rr,_=book.rr(s.d,b.c,s.stop,target.px,market=True)
     if rr>=2:book.order=(s,target)
     else:
      zone=next(((tf,z) for tf in (900,3600) for z in reversed(frames[tf].zones) if z.side==s.d and z.kind in ('OB','FVG','IFVG','Rejection') and s.d*(b.c-(z.hi if s.d==1 else z.lo))>0 and book.rr(s.d,z.hi if s.d==1 else z.lo,s.stop,target.px)[0]>=2),None)
      if not zone or not book.place_limit(s,target,zone[1],zone[0],now):book.reject(now,'no_valid_limit_edge',s)
    else:book.reject(now,'no_unswept_target',s)
    continue
   if s:continue
   if name=='QM_M15':
    if not qm:continue
    d,shoulder,head,ht=qm
    hit=next((a for a in reversed(touches[d]) if a[0]+300<=ht and a[2] in frames[a[1]].zones),None)
    if hit:
     book.setup=Setup(d,hit[2],hit[1],now,head-d*.1,shoulder,shoulder)
     f=frames[900]
     book.setup.evidence=trace(hit,f,900)
     book.setup.evidence['qm_pivots']=[dict(side=p.side,price=p.px,open_utc=utc(p.t)) for p in list(f.pivots)[-4:]]
    continue
   if 900 not in events:continue
   d=events[900];mode=name.split('_')[1];tf={'M15':900,'H1':3600,'H4':14400}[mode]
   if frames[3600].trend!=d:continue
   when=frames[tf].shift_time
   if tf!=900 and (frames[tf].trend!=d or when is None or when>now):continue
   hit=next((a for a in reversed(touches[d]) if a[0]+300<=min(when,now-900) and a[2] in frames[a[1]].zones),None)
   if not hit:continue
   zone=next((z for z in reversed(m15.zones) if z.side==d and z.kind in ('OB','FVG','IFVG') and hit[0]<=z.born<=now and now-z.born<=5400),None)
   anchor=m15.last.get(-d)
   if zone and anchor:
    stop=(min(anchor.px,zone.lo) if d==1 else max(anchor.px,zone.hi))-d*.1
    book.setup=Setup(d,hit[2],hit[1],now,stop,zone.lo,zone.hi)
    book.setup.evidence=trace(hit,m15,900)
    book.setup.evidence.update(retest_type=zone.kind,stop_anchor=anchor.px)
    if tf!=900:book.setup.evidence['higher_shift']=shift_trace(frames[tf],tf)
 if count!=expected_count:raise ValueError(f"evaluation bars: expected {expected_count}, received {count}")
 return books
