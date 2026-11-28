"""Event-driven paper replay on verified Binance USD-M BTCUSDT M5 klines."""
import csv, json, math
from collections import deque, namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from dataset import ROOT,START,END,stamp
Bar=namedtuple('Bar','t o h l c v buy')
Pivot=namedtuple('Pivot','side px t')
Zone=namedtuple('Zone','kind side lo hi born')
Level=namedtuple('Level','side px label')
FEE=.0005
SLIP=.0002
FRAMES=(300,900,3600,14400,86400)
def signprice(d,b): return b.l if d==1 else b.h
def opposite_extreme(d,b):return b.h if d==1 else b.l
def through(d,price,level):return d*(price-level)>0
def overlap(b,z):return b.l<=z.hi and b.h>=z.lo
def utc(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
class Frame:
 def __init__(self,step):
  self.step=step; self.bars=deque(maxlen=16); self.zones=[]; self.pivots=deque(maxlen=10)
  self.last={}; self.broken={}; self.break_time={}; self.shift_time=None; self.trend=0; self.since=None; self.openbar=None
 def feed(self,x):
  t=x.t//self.step*self.step
  a=self.openbar
  if a is None: a=x._replace(t=t)
  else:a=Bar(t,a.o,max(a.h,x.h),min(a.l,x.l),x.c,a.v+x.v,a.buy+x.buy)
  if x.t+300!=t+self.step:
   self.openbar=a; return None
  self.openbar=None;return a
 def close(self,b,now):
  prior=list(self.bars); self.bars.append(b); recent=list(self.bars); newzones=[]
  live=[]
  for z in self.zones:
   if through(-z.side,b.c,z.lo if z.side==1 else z.hi):
    if z.kind in ('OB','FVG'):
     newzones.append(Zone('Breaker' if z.kind=='OB' else 'IFVG',-z.side,z.lo,z.hi,now))
   else:live.append(z)
  if len(prior)>=3:
   a=prior[-1]; left=prior[-2]
   if b.l>left.h:newzones.append(Zone('FVG',1,left.h,b.l,now))
   if b.h<left.l:newzones.append(Zone('FVG',-1,b.h,left.l,now))
   for d in (1,-1):
    level=max(x.h for x in prior[-3:]) if d==1 else min(x.l for x in prior[-3:])
    if d*(a.c-a.o)<0 and through(d,b.c,level):newzones.append(Zone('OB',d,a.l,a.h,now))
    edge=min(x.l for x in prior[-3:]) if d==1 else max(x.h for x in prior[-3:])
    tip=signprice(d,b); body=min(b.c,b.o) if d==1 else max(b.c,b.o)
    if through(-d,tip,edge) and through(d,b.c,edge) and d*(body-tip)>=(b.h-b.l)*.5 and b.h>b.l:
     newzones.append(Zone('Rejection',d,min(tip,body),max(tip,body),now))
  self.zones=(live+newzones)[-80:]
  pivot=None
  if len(recent)>=5:
   w=recent[-5:]; mid=w[2]; peers=w[:2]+w[3:]
   up=all(mid.h>x.h for x in peers); down=all(mid.l<x.l for x in peers)
   if up!=down:
    pivot=Pivot(1 if up else -1, mid.h if up else mid.l,mid.t)
    if not self.pivots or self.pivots[-1].side!=pivot.side:self.pivots.append(pivot)
    elif through(pivot.side,pivot.px,self.pivots[-1].px):self.pivots[-1]=pivot
    self.last[pivot.side]=pivot
  event=None
  for d,p in self.last.items():
   if through(d,b.c,p.px) and self.broken.get(d)!=p.t:
    self.broken[d]=p.t;self.break_time[d]=now
    if self.trend==-d:
     self.shift_time=now;event=d
    self.trend=d;self.since=now
  qm=None
  if pivot and self.pivots[-1]==pivot and len(self.pivots)>=4:
   a,m,k,e=list(self.pivots)[-4:]; d=e.side
   if through(-d,k.px,a.px) and through(d,e.px,m.px) and self.broken.get(d)==m.t and k.t<self.break_time[d]<=e.t+self.step and self.shift_time==self.break_time[d]:
    qm=(d,a.px,k.px,k.t)
  return pivot,event,qm
class Liquidity:
 def __init__(self):self.levels=[]; self.prevday=None;self.session={}
 def bar(self,b):
  self.levels=[l for l in self.levels if (b.h<l.px if l.side==1 else b.l>l.px)]
  day=b.t//86400
  if self.prevday is None or day!=self.prevday[0]:
   if self.prevday:
    _,h,l=self.prevday
    self.levels.extend(x for x in [Level(1,h,'PDH'),Level(-1,l,'PDL')] if (b.h<x.px if x.side==1 else b.l>x.px))
   self.prevday=(day,b.h,b.l)
  else:self.prevday=(day,max(self.prevday[1],b.h),min(self.prevday[2],b.l))
  pl=datetime.fromtimestamp(b.t,PL); hour=pl.hour
  for key,start,end in [('Asia',2,8),('London',9,11),('NY',14,17)]:
   if start<=hour<end:
    old=self.session.get(key,(b.h,b.l));self.session[key]=(max(old[0],b.h),min(old[1],b.l))
   elif key in self.session:
    h,l=self.session.pop(key)
    if b.h<h:self.levels.append(Level(1,h,key+' high'))
    if b.l>l:self.levels.append(Level(-1,l,key+' low'))
 def target(self,d,price):
  return min((p for p in self.levels if p.side==d and through(d,p.px,price)),key=lambda p:abs(p.px-price),default=None)
PL=ZoneInfo('Europe/Warsaw')
@dataclass
class Setup:
 d:int
 z:Zone
 tf:int
 time:int
 stop:float
 lo:float
 hi:float
class Book:
 def __init__(self,name):self.name=name;self.setup=None;self.order=None;self.pos=None;self.rows=[];self.equity=10000.;self.peak=10000.;self.dd=0.;self.mtm_peak=10000.;self.mtm_dd=0.
 def close_pos(self,b,raw,why):
  p=self.pos; d=p['d']; out=raw*(1-d*SLIP)
  pnl=p['funding_cash']+p['qty']*(d*(out-p['entry'])-FEE*(out+p['entry']))
  self.equity+=pnl;self.peak=max(self.peak,self.equity); self.dd=max(self.dd,1-self.equity/self.peak)
  p.update(exit_utc=utc(b.t+300),exit=out,outcome=why,pnl=pnl,R=pnl/p['risk'],equity=self.equity)
  self.rows.append(p);self.pos=None
 def execute(self,b,end,funding):
  if self.pos and b.t in funding:
   rate,mark=funding[b.t]
   self.pos['funding_cash']-=self.pos['d']*self.pos['qty']*rate*mark
  if self.order:
   s,lvl=self.order; self.order=None;d=s.d;entry=b.o*(1+d*SLIP)
   stopout=s.stop*(1-d*SLIP);tpout=lvl.px*(1-d*SLIP)
   loss=d*(entry-stopout)+FEE*(entry+stopout);gain=d*(tpout-entry)-FEE*(entry+tpout)
   if through(d,b.o,s.stop) and loss>0 and gain>=2*loss and self.equity>0:
    budget=self.equity*.01
    qty=math.floor(budget/loss*1000)/1000
    if qty>0:self.pos=dict(model=self.name,d=d,entry_utc=utc(b.t),entry=entry,stop=s.stop,target=lvl.px,target_type=lvl.label,planned_RR=gain/loss,qty=qty,risk=budget,funding_cash=0.,poi=s.z.kind,poi_tf=s.tf,poi_lo=s.z.lo,poi_hi=s.z.hi,retest_lo=s.lo,retest_hi=s.hi,setup_utc=utc(s.time))
  if self.pos:
   p=self.pos;d=p['d']; st=p['stop'];tp=p['target']
   if d*(b.o-st)<=0:self.close_pos(b,b.o,'gap_SL')
   elif d*(b.o-tp)>=0:self.close_pos(b,tp,'TP')
   elif d*(signprice(d,b)-st)<=0:self.close_pos(b,st,'SL')
   elif d*(opposite_extreme(d,b)-tp)>=0:self.close_pos(b,tp,'TP')
   elif b.t+300==end:self.close_pos(b,b.c,'period_end')
  mark=self.equity
  if self.pos:
   p=self.pos;d=p['d'];out=b.c*(1-d*SLIP)
   mark+=p['funding_cash']+p['qty']*(d*(out-p['entry'])-FEE*(out+p['entry']))
  self.mtm_peak=max(self.mtm_peak,mark);self.mtm_dd=max(self.mtm_dd,1-mark/self.mtm_peak)
 def idle(self):return self.pos is None and self.order is None
def backtest(data, funding, expected_count=365*288):
 frames={step:Frame(step) for step in FRAMES}; liq=Liquidity()
 names=['QM_M15']+[f'OF_{tf}_{f}' for tf in ('M5','H1','H4') for f in ('base','weak')]
 books={n:Book(n) for n in names};touches={1:deque(),-1:deque()}
 count=0
 for b in data:
  now=b.t+300;eligible=stamp_start<=b.t<stamp_end
  if eligible:count+=1
  for book in books.values():book.execute(b,stamp_end,funding)
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
  m5=frames[300]
  for name,book in books.items():
   if not book.idle():continue
   s=book.setup
   if s and (s.z not in frames[s.tf].zones or now-s.time>10800 or not through(s.d,signprice(s.d,b),s.stop)):
    book.setup=None;s=None
   if s and now>s.time and b.l<=s.hi and b.h>=s.lo and through(s.d,b.c,(s.lo+s.hi)/2) and s.d*(b.c-b.o)>0:
    book.setup=None
    # Weakness of opposing aggressors: positive signed delta for the opponent,
    # but close back in the setup direction, in outer half of the M5 candle.
    delta=2*b.buy-b.v
    if name.endswith('weak') and not (b.v>0 and s.d*delta/b.v<=-.10 and s.d*(b.c-(b.h+b.l)/2)>0):continue
    target=liq.target(s.d,b.c)
    if target:book.order=(s,target)
    continue
   if s:continue
   if name=='QM_M15':
    if not qm:continue
    d,shoulder,head,ht=qm
    hit=next((a for a in reversed(touches[d]) if a[0]+300<=ht and a[2] in frames[a[1]].zones),None)
    if hit:book.setup=Setup(d,hit[2],hit[1],now,head-d*.1,shoulder,shoulder)
    continue
   if 300 not in events:continue
   d=events[300];mode=name.split('_')[1];tf={'M5':300,'H1':3600,'H4':14400}[mode]
   if frames[3600].trend!=d:continue
   when=frames[tf].shift_time
   if tf!=300 and (frames[tf].trend!=d or when is None or when>=now):continue
   hit=next((a for a in reversed(touches[d]) if a[0]+300<=(when if tf!=300 else now-300) and a[2] in frames[a[1]].zones),None)
   if not hit:continue
   zone=next((z for z in reversed(m5.zones) if z.side==d and z.kind in ('OB','FVG','IFVG') and hit[0]<=z.born<=now and now-z.born<=1800),None)
   anchor=m5.last.get(-d)
   if zone and anchor:
    stop=(min(anchor.px,zone.lo) if d==1 else max(anchor.px,zone.hi))-d*.1
    book.setup=Setup(d,hit[2],hit[1],now,stop,zone.lo,zone.hi)
 assert count==expected_count
 return books
def stats(rows):
 r=[p['R'] for p in rows];wins=[v for v in r if v>0];loss=-sum(v for v in r if v<0)
 positive=sum(p['pnl'] for p in rows if p['pnl']>0);negative=-sum(p['pnl'] for p in rows if p['pnl']<0)
 return dict(n=len(r),pf_cash=positive/negative if negative else None,wr=len(wins)/len(r)*100 if r else None,pf=sum(wins)/loss if loss else None,expect=sum(r)/len(r) if r else None,net=sum(r))
stamp_start,stamp_end=stamp(START),stamp(END)
def main():
 with open(ROOT/'bars.csv') as f: data=[Bar(int(r[0]),*map(float,r[1:])) for r in csv.reader(f)]
 funding={int(k):v for k,v in json.loads((ROOT/'funding.json').read_text()).items()}
 books=backtest(data,funding);out={}
 for k,m in books.items():
  out[k]={**stats(m.rows),'dd_m5_pct':100*m.mtm_dd,'dd_close_pct':100*m.dd,'long':stats([r for r in m.rows if r['d']==1]),'short':stats([r for r in m.rows if r['d']==-1])}
 rows=[r for m in books.values() for r in m.rows]
 if rows:
  with open(ROOT/'trades.csv','w') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 (ROOT/'results.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':main()
