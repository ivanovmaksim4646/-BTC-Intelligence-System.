"""Shared research execution for first-edge limits; frozen baseline untouched."""
from dataclasses import dataclass
import math
from research.baseline import replay as b
from research.runner.confirmed_filters import limit_edge, tighten_stop, protection_trigger

@dataclass
class Pending:
    setup: object
    target: object
    price: float
    zone: object
    tf: int
    created: int

class ExecutionBook(b.Book):
    def __init__(self,name,fee=b.FEE,slip=b.SLIP):
        super().__init__(name,fee,slip)
        self.pending=None
        self.limit_events=[]
        self.fta=None
        self.tracked=None

    def idle(self):
        return super().idle() and self.pending is None

    def rr(self,d,price,stop,target,market=False):
        entry=price*(1+d*self.slip) if market else price
        st=stop*(1-d*self.slip)
        tp=target*(1-d*self.slip)
        loss=d*(entry-st)+self.fee*(entry+st)
        gain=d*(tp-entry)-self.fee*(entry+tp)
        return (gain/loss,loss) if loss>0 and d*(entry-stop)>0 else (0,0)

    def place_limit(self,s,target,zone,tf,now):
        px=limit_edge(s.d,zone.lo,zone.hi)
        rr,_=self.rr(s.d,px,s.stop,target.px)
        if not self.idle() or rr<2:
            return False
        self.pending=Pending(s,target,px,zone,tf,now)
        self.limit_events.append(dict(event="placed",time=b.utc(now),price=px,side=s.d))
        return True

    def cancel(self,now,reason):
        p=self.pending
        if p is None:return
        self.reject(now,reason,p.setup)
        self.limit_events.append(dict(event=reason,time=b.utc(now),price=p.price,side=p.setup.d,
                                      target=p.target.px,stop=p.setup.stop))
        self.pending=None

    def execute(self,bar,end,funding):
        p=self.pending
        if p and bar.t>=p.created:
            s=p.setup; d=s.d
            touch=d*(b.signprice(d,bar)-p.price)<=0
            target=d*(b.opposite_extreme(d,bar)-p.target.px)>=0
            stop=d*(b.signprice(d,bar)-s.stop)<=0
            if d*(bar.o-p.target.px)>=0 or (target and not touch):
                self.cancel(bar.t+300,"limit_target_before_fill")
            elif stop and d*(bar.o-s.stop)<=0:
                self.cancel(bar.t,"limit_gap_invalidation")
            elif touch and target and not stop and d*(bar.o-p.price)>0:
                # Intrabar order unknown: do not claim a winning execution.
                self.cancel(bar.t+300,"limit_ambiguous_target_fill")
            elif touch:
                rr,loss=self.rr(d,p.price,s.stop,p.target.px)
                budget=self.equity*.01
                qty=math.floor(budget/loss*1000)/1000 if loss>0 else 0
                if rr>=2 and qty>0:
                    self.pos=dict(model=self.name,d=d,entry_utc=b.utc(bar.t),entry=p.price,
                        stop=s.stop,initial_stop=s.stop,target=p.target.px,target_type=p.target.label,
                        planned_RR=rr,qty=qty,risk=budget,funding_cash=0.,poi=s.z.kind,poi_tf=s.tf,
                        poi_lo=s.z.lo,poi_hi=s.z.hi,retest_lo=p.zone.lo,retest_hi=p.zone.hi,
                        setup_utc=b.utc(s.time),evidence=dict(s.evidence,entry_mode="limit",
                        limit_placed_utc=b.utc(p.created),limit_zone_type=p.zone.kind))
                    self.limit_events.append(dict(event="filled",time=b.utc(bar.t),price=p.price,side=d))
                    self.pending=None
                    # Funding at bar open precedes an intrabar limit fill. Suppress it for this bar.
                    funding={} 
                else:self.cancel(bar.t,"limit_rr_or_quantity_invalid")
            elif bar.t+300>=end:self.cancel(end,"limit_period_end")
        super().execute(bar,end,funding)

    def after_close(self,bar,frames,events):
        now=bar.t+300
        p=self.pending
        if p:
            d=p.setup.d
            if p.zone not in frames[p.tf].zones or p.setup.z not in frames[p.setup.tf].zones:
                self.cancel(now,"limit_poi_invalidated")
            elif any(events.get(tf)==-d for tf in (300,900)) and any(
                z.side==-d and b.overlap(bar,z) and z.born<=bar.t
                for tf in (900,3600,14400) for z in frames[tf].zones):
                self.cancel(now,"limit_opposing_fta_shift")
        p=self.pos
        if not p:
            self.fta=None;self.tracked=None;return
        d=p["d"];p.setdefault("initial_stop",p["stop"])
        risk=abs(p["entry"]-p["initial_stop"])
        if self.tracked!=p["entry_utc"]:
            self.tracked=p["entry_utc"];self.fta=None
        active=[(tf,z) for tf in (14400,3600,900) for z in frames[tf].zones
                if z.side==-d and z.born<=bar.t]
        if self.fta not in active:self.fta=None
        hit=next(((tf,z) for tf,z in active if b.overlap(bar,z)),None)
        if hit:self.fta=hit
        if not self.fta or not risk:return
        tf,z=self.fta
        distance=max(0,d*((z.lo if d==1 else z.hi)-p["entry"])/risk)
        shift=next((step for step in (900,300) if protection_trigger(
            d,distance,True,events.get(step),step,step in events)),None)
        if not shift:return
        old=p["stop"]
        new=tighten_stop(d,old,p["entry"],bar.c)
        if new!=old:
            p["stop"]=new
            p.setdefault("management",[]).append(dict(time=b.utc(now),reason="FTA_BE",
                tf=tf,shift_tf=shift,old_stop=old,new_stop=new))
        self.fta=None
