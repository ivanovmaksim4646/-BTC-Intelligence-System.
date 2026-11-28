"""Research-only SL/TP comparison on the pinned Binance USD-M archive.

Reuses baseline Frame/POI/QM and verified input reader. Ten configured independent
accounts with one fixed buffer and auditable structural decisions. This is a new research proxy, not the live OKX signal algorithm.
No order submission, no changes to main, no historical CVD/orderbook claims.
"""
import json
import math
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from research.baseline import replay as b
from research.baseline.dataset import START, END, stamp
from research.runner.inputs import verified_bars, verified_funding

UTC=ZoneInfo("UTC")
PL=ZoneInfo("Europe/Warsaw")
LONDON=ZoneInfo("Europe/London")
NY=ZoneInfo("America/New_York")
DAY=86400
BUFFERS=(3,)  # Existing production buffer; not optimized.
MODELS=("QM_M15",)+tuple(f"OF_{tf}_{variant}" for tf in ("M5","M15","H1","H4") for variant in ("base","weak"))+("IB_M15_market",)
TTL=900
MAX_AGE=10800
ALLOWED_POI={"OB","FVG","IFVG","Rejection"}

def hit(direction,bar,level):
    return bar.h>=level if direction==1 else bar.l<=level

def stop_hit(direction,bar,level):
    return bar.l<=level if direction==1 else bar.h>=level

class Levels:
    """Only levels confirmed before evaluation, removed on first wick touch."""
    def __init__(self):
        self.live=set()
        self.ranges={}
        self.sweeps={1:None,-1:None}
    def add(self,side,price,label,external):
        self.live.add((side,price,label,external))
    def bar(self,x):
        now=x.t+300
        u=datetime.fromtimestamp(x.t,UTC)
        p=u.astimezone(PL); l=u.astimezone(LONDON); n=u.astimezone(NY)
        ranges={
            "day":(u.date(),u.hour==0 and u.minute==0),
            "month":((u.year,u.month),u.day==1 and u.hour==0 and u.minute==0),
            "Asia":(p.date() if 2<=p.hour<8 else None,p.hour==2 and p.minute==0),
            "London":(l.date() if 8<=l.hour<10 else None,l.hour==8 and l.minute==0),
            "NY":(n.date() if 8<=n.hour<11 else None,n.hour==8 and n.minute==0),
        }
        for label,(key,first) in ranges.items():
            old=self.ranges.get(label)
            if old and old[0]!=key:
                if old[3]:
                    hi,lo={"day":("PDH","PDL"),"month":("PMH","PML")}.get(label,(label+" high",label+" low"))
                    self.add(1,old[1],hi,True);self.add(-1,old[2],lo,True)
                self.ranges.pop(label)
                old=None
            if key is not None:
                self.ranges[label]=(key,max(old[1],x.h),min(old[2],x.l),old[3]) if old else (key,x.h,x.l,first)
        for d,s in list(self.sweeps.items()):
            if s and (now-s["close"]>MAX_AGE or (x.h>s["extreme"] if d==-1 else x.l<s["extreme"])):
                self.sweeps[d]=None
        touched=[v for v in self.live if hit(v[0],x,v[1])]
        for side,price,label,external in sorted(touched,key=lambda v:(v[0],v[1],v[2],v[3])):
            self.live.remove((side,price,label,external))
            if external and side*(x.c-price)<0 and (x.h>price if side==1 else x.l<price):
                d=-side
                proposal={"close":now,"level":price,"label":label,"extreme":x.h if side==1 else x.l}
                old=self.sweeps[d]
                if old is None or old["close"]!=now or side*(price-old["level"])>0:
                    self.sweeps[d]=proposal
    def pivot(self,p,tf):
        if p and tf>=900:
            self.add(p.side,p.px,"swing "+str(tf//60)+"m",tf>=3600)

def structural_targets(d,entry,frames,levels,filled,shift_price=None,shift_time=None,first_tests=None,fixed_target=None):
    """External target is chosen by structure BEFORE RR, not by desired R."""
    pivot=frames[900].last.get(d)
    boundary=pivot.px if pivot and d*(pivot.px-entry)>0 else entry
    profits=[(px,label,ext) for side,px,label,ext in levels.live if side==d and d*(px-entry)>0]
    external=[(px,label) for px,label,ext in profits if ext and d*(px-boundary)>=0]
    external.sort(key=lambda v:(abs(v[0]-entry),v[1]))
    if fixed_target is None:
        if not external:return None,"no_external_liquidity"
        tp,target_kind=external[0]
    else:
        tp,target_kind=fixed_target
        if d*(tp-entry)<=0:return None,"invalid_range_target"
    fta_candidates=[(px,label,None) for px,label,_ in profits if d*(tp-px)>=0]
    fta_candidates.append((tp,target_kind,None))
    overlaps=[]
    shift_inside=[]
    tested_ignored=[]
    first_tests={} if first_tests is None else first_tests
    # Distinguish the confirmed shift CLOSE from a hypothetical limit price.
    # An opposing zone formed after the shift cannot retrospectively veto it.
    for tf in (900,3600,14400,86400):
        for z in frames[tf].zones:
            if z.kind not in ALLOWED_POI or z in filled or z.side==d:continue
            first=first_tests.get((tf,z))
            zone=dict(kind=z.kind,tf=tf,low=z.lo,high=z.hi,formed_utc=b.utc(z.born),
                      first_test_utc=b.utc(first) if first is not None else None)
            if (shift_price is not None and shift_time is not None and z.born<shift_time
                    and z.lo<=shift_price<=z.hi and (first is None or first>=shift_time)):
                shift_inside.append(zone)
            if first is not None:
                tested_ignored.append(zone)
                continue
            if z.lo<=entry<=z.hi:
                # A limit in a live opposing zone needs a fresh post-
                # invalidation setup; retain precise evidence for review.
                overlaps.append(zone)
                continue
            edge=z.lo if d==1 else z.hi
            if d*(edge-entry)>0 and d*(tp-edge)>=0:
                fta_candidates.append((edge,"opposing_"+z.kind+"_"+str(tf//60)+"m",zone))
    fta,fta_kind,fta_zone=min(fta_candidates,key=lambda v:(abs(v[0]-entry),v[1]))
    result=dict(target=tp,target_kind=target_kind,fta=fta,fta_kind=fta_kind,fta_zone=fta_zone,
                external_boundary=boundary,overlap_zones=overlaps,shift_inside_zones=shift_inside,
                previously_tested_ignored_count=len(tested_ignored),
                target_ladder=[{"price":p,"kind":k} for p,k in external[:12]])
    if shift_inside:return result,"shift_inside_active_fta"
    if overlaps:return result,"limit_inside_active_opposing_zone"
    return result,None

class Account:
    def __init__(self,model,buffer,fee,slip):
        self.model=model;self.buffer=buffer;self.fee=fee;self.slip=slip
        self.name=f"{model}_B{buffer:02d}"
        self.equity=1000.;self.peak=1000.;self.dd=0.
        self.setup=None;self.pending=None;self.pos=None;self.ready=None
        self.rows=[];self.rejects=Counter();self.events=0;self.audit=[];self.current_audit=None
    def idle(self):return self.setup is None and self.pending is None and self.pos is None and self.ready is None
    def reject(self,why):
        self.rejects[why]+=1
        if self.current_audit is not None:
            self.current_audit["events"].append(why)
    def audit_idea(self,idea,targets,now):
        clean={k:(v._asdict() if hasattr(v,"_asdict") else v) for k,v in idea.items()}
        self.current_audit={"at_utc":b.utc(now),"idea":clean,"targets":targets,"events":[]}
        self.audit.append(self.current_audit)
    def propose(self,idea,targets,now,bar):
        self.events+=1
        self.audit_idea(idea,targets,now)
        if not targets:self.reject("no_target");return
        d=idea["d"];e=idea["entry_limit"]
        s=idea["anchor"]*(1-d*self.buffer/10000)
        if d*(e-s)<=0:self.reject("invalid_stop");return
        self.current_audit["initial_sl"]=s
        # The confirmation candle predates the order. Its wick alone is not
        # a pending-order cancellation; a close beyond FTA still rejects.
        if stop_hit(d,bar,s):
            self.reject("structural_stop_breached_on_confirmation");return
        # A confirmed break beyond a former FTA is not an automatic veto.
        # The final TP must still be unswept; later retest must revalidate FTA.
        if d*(bar.c-targets["target"])>=0:
            self.reject("target_already_reached");return
        entry=e*(1+d*self.slip)
        stop=s*(1-d*self.slip)
        target=targets["target"]*(1-d*self.slip)
        loss=d*(entry-stop)+self.fee*(entry+stop)
        gain=d*(target-entry)-self.fee*(entry+target)
        self.current_audit["net_rr"]=gain/loss if loss>0 else None
        self.current_audit["gross_rr"]=d*(targets["target"]-e)/abs(e-s)
        self.current_audit["stop_distance_pct"]=100*abs(e-s)/e
        self.current_audit["target_distance_pct"]=100*abs(targets["target"]-e)/e
        if loss<=0 or gain<2*loss:self.reject("net_rr_below_two");return
        self.setup={**idea,**targets,"stop":s,"born":now,"loss_per_btc":loss,"planned_rr":gain/loss}
        self.current_audit["events"].append("setup_accepted")
        if self.model=="IB_M15_market":
            self.pending={**self.setup,"market_next_open":True,"expires":now+300}
            self.setup=None
            self.current_audit["events"].append("market_order_scheduled")
    def close(self,x,raw,outcome):
        p=self.pos;d=p["d"]
        price=raw*(1-d*self.slip)
        pnl=p["funding"]+p["qty"]*(d*(price-p["entry"])-self.fee*(price+p["entry"]))
        self.equity+=pnl
        self.rows.append({**p,"exit_utc":b.utc(x.t+300),"exit":price,"outcome":outcome,"pnl":pnl,
                          "R":pnl/p["risk"],"equity":self.equity})
        if self.current_audit is not None:self.current_audit["events"].append(outcome)
        self.pos=None
    def on_bar(self,x,now,end,funding,frames,filled):
        if self.pos and x.t in funding:
            rate,mark=funding[x.t]
            self.pos["funding"]-=self.pos["d"]*self.pos["qty"]*rate*mark
        if self.pending:
            p=self.pending;d=p["d"];e=p["entry_limit"]
            if p.get("market_next_open"):
                raw=x.o;entry=raw*(1+d*self.slip)
                stop=p["stop"]*(1-d*self.slip);target=p["target"]*(1-d*self.slip)
                loss=d*(entry-stop)+self.fee*(entry+stop)
                gain=d*(target-entry)-self.fee*(entry+target)
                if d*(raw-p["stop"])<=0 or d*(p["fta"]-raw)<=0 or loss<=0 or gain<2*loss:
                    self.reject("market_open_invalid_or_rr_below_two")
                else:
                    qty=math.floor(min(self.equity*.01/loss,self.equity*5/entry)*1000)/1000
                    if qty>0:
                        self.pos={**p,"entry_limit":raw,"model":self.name,"entry":entry,"entry_utc":b.utc(x.t),
                                  "fill_t":x.t,"qty":qty,"risk":qty*loss,"funding":0.,"active_stop":p["stop"],
                                  "be_trigger":None,"planned_rr":gain/loss}
                        self.current_audit["events"].append("market_filled")
                    else:self.reject("quantity_below_step")
                self.pending=None
            touch=x.l<=e<=x.h
            fta=hit(d,x,p["fta"]);stop=stop_hit(d,x,p["stop"])
            zone=p.get("zone")
            valid=zone is None or (zone in frames[p["poi_tf"]].zones and zone not in filled)
            if p.get("market_next_open"):pass
            elif not valid:
                self.reject("pending_poi_invalidated");self.pending=None
            elif x.t>=p["expires"]:
                self.reject("expired_limit");self.pending=None
            elif fta or stop:
                self.reject("censored_fill_bar" if touch else "fta_or_stop_before_fill");self.pending=None
            elif touch:
                fill=e*(1+d*self.slip)
                qty=math.floor(min(self.equity*.01/p["loss_per_btc"],self.equity*5/fill)*1000)/1000
                if qty>0:
                    self.pos={**p,"model":self.name,"entry":fill,"entry_utc":b.utc(x.t),"fill_t":x.t,
                              "qty":qty,"risk":qty*p["loss_per_btc"],"funding":0.,"active_stop":p["stop"],"be_trigger":None}
                else:self.reject("quantity_below_step")
                if self.pos and self.current_audit is not None:self.current_audit["events"].append("limit_filled")
                self.pending=None
        if self.pos:
            p=self.pos;d=p["d"];s=p["active_stop"];tp=p["target"]
            # Stop-first on ambiguity; new BE can only apply next candle.
            if d*(x.o-s)<=0:
                self.close(x,x.o,"BE" if p["be_trigger"] and x.o==p["entry_limit"] else "gap_SL")
            elif stop_hit(d,x,s):
                self.close(x,s,"BE" if p["be_trigger"] else "SL")
            elif hit(d,x,tp):
                self.close(x,tp,"TP")
            elif now==end:self.close(x,x.c,"period_end")
        if self.setup:
            s=self.setup;d=s["d"]
            zone=s.get("zone")
            valid=zone is None or (zone in frames[s["poi_tf"]].zones and zone not in filled)
            if not valid or now-s["born"]>MAX_AGE:
                self.reject("setup_invalidated_or_expired");self.setup=None
            elif hit(d,x,s["target"]) or stop_hit(d,x,s["stop"]):
                self.reject("target_or_stop_before_retest");self.setup=None
            elif now>s["born"] and x.l<=s["hi"] and x.h>=s["lo"] and d*(x.c-(s["lo"]+s["hi"])/2)>0 and d*(x.c-x.o)>0:
                # Delay placement until all current closed frames update.
                # FTA may have been invalidated during the setup phase.
                delta=2*x.buy-x.v
                if self.model.endswith("_weak") and not (x.v>0 and d*delta/x.v<=-.10 and d*(x.c-(x.h+x.l)/2)>0):
                    self.reject("weakness_filter")
                else:self.ready={**s,"expires":now+TTL,"retest_close_utc":b.utc(now)}
                self.setup=None
        mark=self.equity
        if self.pos:
            p=self.pos;out=x.c*(1-p["d"]*self.slip)
            mark+=p["funding"]+p["qty"]*(p["d"]*(out-p["entry"])-self.fee*(out+p["entry"]))
        self.peak=max(self.peak,mark);self.dd=max(self.dd,1-mark/self.peak)
    def place_ready(self,frames,levels,filled,x,now,first_tests=None):
        if self.ready is None:return
        s=self.ready;self.ready=None
        d=s["d"]
        zone=s.get("zone")
        if zone is not None and (zone not in frames[s["poi_tf"]].zones or zone in filled):
            self.reject("poi_invalidated_on_retest");return
        targets,reason=structural_targets(d,s["entry_limit"],frames,levels,filled,first_tests=first_tests)
        if self.current_audit is not None:self.current_audit["retest_targets"]=targets
        if reason:self.reject("retest_"+reason);return
        # The TP is frozen at the original decision. Never extend it to
        # manufacture RR after a nearer objective is swept.
        if not any(side==d and px==s["target"] and ext for side,px,_,ext in levels.live):
            self.reject("original_target_no_longer_unswept");return
        if d*(targets["fta"]-s["target"])>0:
            targets.update(fta=s["target"],fta_kind=s["target_kind"],fta_zone=None)
        if d*(x.c-targets["fta"])>=0:
            self.reject("fta_already_reached_at_limit_placement");return
        self.pending={**s,**{k:targets[k] for k in ("fta","fta_kind","fta_zone")}}
        if self.current_audit is not None:self.current_audit["events"].append("limit_placed")
    def after_close(self,x,now,m5_shift):
        p=self.pos
        if not p or p["be_trigger"] or x.t<=p["fill_t"]:return
        d=p["d"]
        trigger="fta_test" if hit(d,x,p["fta"]) else "m5_shift" if m5_shift==d and d*(x.c-p["entry_limit"])>0 else None
        if trigger:
            p.update(active_stop=p["entry_limit"],be_trigger=trigger,be_effective_utc=b.utc(now))
    def report(self):
        rows=self.rows
        outcomes=Counter(r["outcome"] for r in rows)
        wins=sum(r["pnl"]>0 for r in rows if r["outcome"]!="BE")
        losses=sum(r["pnl"]<=0 for r in rows if r["outcome"]!="BE")
        pos=sum(max(0,r["pnl"]) for r in rows)
        neg=-sum(min(0,r["pnl"]) for r in rows)
        return dict(model=self.model,buffer_bps=self.buffer,events=self.events,trades=len(rows),wins=wins,losses=losses,
                    be=outcomes["BE"],win_rate_pct=100*wins/(wins+losses) if wins+losses else None,
                    expectancy_r=sum(r["R"] for r in rows)/len(rows) if rows else None,
                    net_r=sum(r["R"] for r in rows),pnl_usd=self.equity-1000,equity=self.equity,
                    profit_factor=pos/neg if neg else None,drawdown_pct=100*self.dd,
                    outcomes=dict(outcomes),rejections=dict(self.rejects),
                    pending_at_end=int(self.pending is not None),setup_at_end=int(self.setup is not None))

def run(bars,funding,start,end,fee=.0005,slip=.0002):
    if not bars or bars[0].t!=start-30*DAY or bars[-1].t!=end-300 or any(v.t-u.t!=300 for u,v in zip(bars,bars[1:])):
        raise ValueError("archive continuity/warmup")
    frames={tf:b.Frame(tf) for tf in b.FRAMES}
    levels=Levels();filled=set();first_tests={};shift_fresh={}
    touches={1:deque(),-1:deque()}
    accounts=[Account(m,k,fee,slip) for m in MODELS for k in BUFFERS]
    count=0;daily=None;bounds=None;excursion={}
    for x in bars:
        now=x.t+300;eligible=start<=x.t<end
        if eligible:count+=1
        # Wick full-fill retires an imbalance only; OB/Breaker/Rejection
        # use existing timeframe-close invalidation in Frame.close.
        for tf,f in frames.items():
            for z in f.zones:
                if tf>=900 and z.kind in ALLOWED_POI and z.born<=x.t and b.overlap(x,z):
                    first_tests.setdefault((tf,z),now)
                if z.kind in ("FVG","IFVG") and z.born<=x.t and (x.l<=z.lo if z.side==1 else x.h>=z.hi):filled.add(z)
        if eligible:
            for a in accounts:a.on_bar(x,now,end,funding,frames,filled)
        levels.bar(x)
        for d in (1,-1):
            q=touches[d]
            while q and x.t-q[0][0]>MAX_AGE:q.popleft()
            choice=None
            for tf in (86400,14400,3600):
                for z in reversed(frames[tf].zones):
                    if z.kind in ALLOWED_POI and z not in filled and z.side==d and b.overlap(x,z) and b.through(d,x.c,(z.lo+z.hi)/2) and d*(x.c-x.o)>0:
                        choice=(x.t,tf,z);break
                if choice:break
            if choice:q.append(choice)
        if bounds:
            lo,hi=bounds
            for d in (1,-1):
                extreme=x.l if d==1 else x.h
                if (extreme<lo if d==1 else extreme>hi):
                    prior=excursion.get(d)
                    if prior is None or d*(extreme-prior[0])<0:
                        excursion[d]=(extreme,prior[1] if prior else None)
                if d in excursion:
                    hit_zone=next(((tf,z) for tf in (86400,14400,3600) for z in reversed(frames[tf].zones)
                                  if z.kind in ALLOWED_POI and z not in filled and z.side==d and b.overlap(x,z) and d*(x.c-x.o)>0),None)
                    if hit_zone:excursion[d]=(excursion[d][0],hit_zone)
        shifts={};qm=None
        for tf in b.FRAMES:
            f=frames[tf];bar=f.feed(x)
            if bar is None:continue
            pivot,event,pattern=f.close(bar,now)
            if event:shifts[tf]=event
            if tf==900:qm=pattern
            if tf==86400:
                if daily and bar.h<daily.h and bar.l>daily.l:bounds=(bar.l,bar.h);excursion={}
                elif bounds and (bar.c<bounds[0] or bar.c>bounds[1]):bounds=None;excursion={}
                daily=bar
            levels.pivot(pivot,tf)
        filled.intersection_update(z for f in frames.values() for z in f.zones)
        live_keys={(tf,z) for tf,f in frames.items() if tf>=900 for z in f.zones}
        first_tests={k:t for k,t in first_tests.items() if k in live_keys}
        # Preserve event-time state for QM, confirmed after its shift.
        for tf,direction in shifts.items():
            if tf not in (300,900):continue
            f=frames[tf];price=f.shift_close
            zones=[]
            for ztf in (900,3600,14400,86400):
                for z in frames[ztf].zones:
                    first=first_tests.get((ztf,z))
                    if (z.kind in ALLOWED_POI and z not in filled and z.side!=direction
                            and z.born<now and z.lo<=price<=z.hi and (first is None or first>=now)):
                        zones.append(dict(kind=z.kind,tf=ztf,low=z.lo,high=z.hi,
                                          formed_utc=b.utc(z.born),first_test_utc=b.utc(first) if first is not None else None))
            shift_fresh[(tf,now,direction)]=zones
        shift_fresh={k:v for k,v in shift_fresh.items() if now-k[1]<=MAX_AGE}
        if not eligible:continue
        for a in accounts:
            a.after_close(x,now,shifts.get(300))
            a.place_ready(frames,levels,filled,x,now,first_tests)
        if now>=end:continue
        ideas={}
        if qm:
            d,shoulder,head,ht=qm
            hit_zone=next((v for v in reversed(touches[d]) if v[0]+300<=ht and v[2] in frames[v[1]].zones and v[2] not in filled),None)
            if hit_zone:
                _,tf,z=hit_zone
                ideas["QM_M15"]=dict(d=d,anchor=head,anchor_kind="confirmed_M15_QM_head",anchor_at=b.utc(ht),entry_limit=shoulder,lo=shoulder,hi=shoulder,zone=z,poi_tf=tf,poi=z.kind,poi_touch_utc=b.utc(hit_zone[0]),shift_utc=b.utc(frames[900].shift_time),shift_price=frames[900].shift_close,shift_time=frames[900].shift_time,setup_utc=b.utc(now))
        d=shifts.get(300)
        if d and frames[3600].trend==d:
            for name,tf_mode in (("M5",300),("M15",900),("H1",3600),("H4",14400)):
                f=frames[tf_mode];when=f.shift_time
                if tf_mode!=300 and (f.trend!=d or when is None or when>=now):continue
                cutoff=when if tf_mode!=300 else now-300
                hit_zone=next((v for v in reversed(touches[d]) if v[0]+300<=cutoff and v[2] in frames[v[1]].zones and v[2] not in filled),None)
                if not hit_zone:continue
                local=next((z for z in reversed(frames[300].zones) if z.side==d and z.kind in ("OB","FVG","IFVG") and z not in filled and hit_zone[0]<=z.born<=now and now-z.born<=1800),None)
                if not local:continue
                _,tf,z=hit_zone
                edge=local.lo if d==1 else local.hi
                protected=frames[300].last.get(-d)
                relevant=protected is not None and hit_zone[0]<=protected.t<now and d*(protected.px-edge)<=0
                anchor=protected.px if relevant else edge
                idea=dict(d=d,anchor=anchor,anchor_kind="protecting_swing" if relevant else "entry_zone_invalidation",
                          anchor_at=b.utc(protected.t if relevant else local.born),entry_limit=local.hi if d==1 else local.lo,
                          lo=local.lo,hi=local.hi,zone=z,poi_tf=tf,poi=z.kind,entry_zone=local.kind,
                          poi_touch_utc=b.utc(hit_zone[0]),shift_utc=b.utc(now),shift_price=frames[300].shift_close,
                          shift_time=now,confirmation_tf=tf_mode,setup_utc=b.utc(now))
                for variant in ("base","weak"):ideas[f"OF_{name}_{variant}"]=dict(idea)
        d=shifts.get(900)
        if d and bounds and d in excursion:
            lo,hi=bounds;extreme,hit_zone=excursion[d]
            if hit_zone and lo<x.c<hi:
                tf,z=hit_zone
                if z in frames[tf].zones and z not in filled and (extreme<lo if d==1 else extreme>hi):
                    ideas["IB_M15_market"]=dict(d=d,anchor=extreme,anchor_kind="IB_deviation_extreme",entry_limit=x.c,
                        lo=x.c,hi=x.c,zone=z,poi_tf=tf,poi=z.kind,range_low=lo,range_high=hi,
                        fixed_target=(hi if d==1 else lo,"opposite_IB_boundary"),
                        shift_price=frames[900].shift_close,shift_time=now,setup_utc=b.utc(now))
                    excursion.pop(d,None)
        for model,idea in ideas.items():
            targets,reason=structural_targets(idea["d"],idea["entry_limit"],frames,levels,filled,first_tests=first_tests,fixed_target=idea.get("fixed_target"))
            event_tf=300 if model.startswith("OF_") else 900
            event_key=(event_tf,idea["shift_time"],idea["d"])
            if targets is not None:
                targets["shift_inside_zones"]=shift_fresh.get(event_key,[])
                if event_key not in shift_fresh:reason="missing_shift_freshness_snapshot"
                elif targets["shift_inside_zones"]:reason="shift_inside_fresh_fta"
            for a in accounts:
                if a.model!=model or not a.idle():continue
                if reason:a.events+=1;a.audit_idea(idea,targets,now);a.reject(reason)
                else:a.propose(idea,targets,now,x)
    if count!=(end-start)//300:raise ValueError("evaluation coverage")
    return accounts

def self_test():
    from types import SimpleNamespace
    f={tf:SimpleNamespace(last={},zones=[]) for tf in b.FRAMES}
    f[900].last[1]=b.Pivot(1,103,0)
    lv=Levels();lv.add(1,102,"internal",False);lv.add(1,106,"external",True);lv.add(1,110,"external2",True)
    result,err=structural_targets(1,100,f,lv,set())
    assert err is None and result["fta"]==102 and result["target"]==106
    a=Account("QM_HEAD",3,.0005,.0002)
    a.propose(dict(d=1,entry_limit=100,anchor=99,lo=100,hi=100,zone=None,poi_tf=900),result,300,b.Bar(0,100,101,99.5,100,1,0))
    assert a.setup and a.setup["stop"]<99
    a.on_bar(b.Bar(300,100,101,99.8,100.5,1,0),600,3600,{},f,set())
    a.place_ready(f,lv,set(),b.Bar(300,100,101,99.8,100.5,1,0),600)
    assert a.pending and not a.pos
    a.on_bar(b.Bar(600,100.5,101,99.9,100.2,1,0),900,3600,{},f,set())
    assert a.pos and a.pos["risk"]<=10+1e-8
    a.on_bar(b.Bar(900,100.2,102.2,99.5,101.5,1,0),1200,3600,{},f,set())
    assert a.pos and a.pos["active_stop"]<99
    a.after_close(b.Bar(900,100.2,102.2,99.5,101.5,1,0),1200,None)
    assert a.pos["active_stop"]==100
    a.on_bar(b.Bar(1200,101,101.2,99.9,100,1,0),1500,3600,{},f,set())
    assert a.rows[-1]["outcome"]=="BE" and a.rows[-1]["pnl"]<0
    a=Account("QM_HEAD",3,.0005,.0002)
    a.propose(dict(d=1,entry_limit=100,anchor=99,lo=100,hi=100,zone=None,poi_tf=900),result,300,b.Bar(0,100,102.2,99.5,100,1,0))
    assert a.setup and a.current_audit["events"]==["setup_accepted"]
    a=Account("QM_HEAD",3,.0005,.0002)
    a.propose(dict(d=1,entry_limit=100,anchor=99,lo=100,hi=100,zone=None,poi_tf=900),result,300,b.Bar(0,100,103,99.5,102.2,1,0))
    assert a.setup
    # BB excluded; shift inside preexisting OB still blocks with evidence.
    f[3600].zones=[b.Zone("Breaker",-1,99,104,0)]
    result,err=structural_targets(1,100,f,lv,set(),103,300)
    assert err is None and result["fta"]==102
    f[3600].zones.append(b.Zone("OB",-1,102,104,0))
    result,err=structural_targets(1,100,f,lv,set(),103,300)
    assert err=="shift_inside_active_fta" and result["shift_inside_zones"][0]["kind"]=="OB"
    f[3600].zones=[b.Zone("FVG",-1,99,101,0)]
    result,err=structural_targets(1,100,f,lv,set(),103,300)
    assert err=="limit_inside_active_opposing_zone" and result["overlap_zones"][0]["kind"]=="FVG"
    z=f[3600].zones[0]
    result,err=structural_targets(1,100,f,lv,set(),103,300,first_tests={(3600,z):100})
    assert err is None and result["fta"]==102
    z=b.Zone("OB",-1,102,104,0)
    f[3600].zones=[z]
    result,err=structural_targets(1,100,f,lv,set(),103,300,first_tests={(3600,z):300})
    assert err=="shift_inside_active_fta"
    result,err=structural_targets(1,100,f,lv,set(),103,300,first_tests={(3600,z):200})
    assert err is None
    f[900].last[-1]=b.Pivot(-1,97,0)
    lv.add(-1,94,"external",True)
    z=b.Zone("OB",1,96,98,0);f[3600].zones=[z]
    result,err=structural_targets(-1,100,f,lv,set(),97,300,first_tests={(3600,z):100})
    assert err is None and result["fta"]==94

def main():
    self_test()
    configured=json.loads(Path(__file__).with_name("config.json").read_text())["models"]
    assert tuple(configured)==MODELS and len(MODELS)==10
    bars,pins=verified_bars(START,END,Path(".research-cache"))
    start,end=stamp(START),stamp(END)
    funding=verified_funding(start,end)
    cut=start+int((end-start)//DAY*.75)*DAY
    def window(lo,hi,fee=.0005,slip=.0002):
        sample=[x for x in bars if lo-30*DAY<=x.t<hi]
        return run(sample,funding,lo,hi,fee,slip)
    full=window(start,end)
    train=window(start,cut)
    test=window(cut,end)
    stress=window(start,end,.0007,.0003)
    train_stats={a.name:a.report() for a in train}
    holdout_stats={a.name:a.report() for a in test}
    selected={}
    for m in MODELS:
        eligible=[a for a in train if a.model==m and a.report()["trades"]>=5]
        best=max(eligible,key=lambda a:a.report()["expectancy_r"],default=None)
        selected[m]={"chosen_before_holdout":best.name if best else None,"holdout":holdout_stats[best.name] if best else None}
    tp_diagnostics={}
    for a in full:
        rejected=[x for x in a.audit if "net_rr_below_two" in x["events"]]
        counts=Counter(x["targets"]["target_kind"] for x in rejected)
        eligible_htf=0
        # Diagnostic only: first major known liquidity level, not chosen
        # according to its RR and never used to change an actual trade.
        for x in rejected:
            idea=x["idea"];d=idea["d"];e=idea["entry_limit"];s=x["initial_sl"]
            if idea.get("fixed_target"):continue
            major=next((v for v in x["targets"]["target_ladder"] if v["kind"] in ("PDH","PDL","PMH","PML","swing 240m","swing 1440m")),None)
            if major:
                en=e*(1+d*a.slip);st=s*(1-d*a.slip);tp=major["price"]*(1-d*a.slip)
                loss=d*(en-st)+a.fee*(en+st);gain=d*(tp-en)-a.fee*(en+tp)
                if loss>0:
                    x["diagnostic_major_target"]={**major,"net_rr":gain/loss,"not_traded":True}
                    eligible_htf+=int(gain>=2*loss)
        tp_diagnostics[a.name]={"rr_rejections":len(rejected),"gross_ge_2_net_below_2":sum(x.get("gross_rr",0)>=2 for x in rejected),
                                "first_major_liquidity_net_ge_2_diagnostic_only":eligible_htf,
                                "target_types":dict(counts),"examples":rejected[:2]}
    report={"tp_diagnostics":tp_diagnostics,"classification":"historical_research_only","instrument":"Binance USD-M BTCUSDT",
            "period_utc":[b.utc(start),b.utc(end)],"evaluation_m5":(end-start)//300,
            "warmup_days":30,"archive_sha256":pins,"funding_settlements":len(funding),
            "initial_usd":1000,"risk_fraction":.01,"leverage_cap":5,"min_net_rr":2,
            "fee_bps_per_side":5,"slippage_bps_per_side":2,"buffer_bps":BUFFERS,
            "train_cut_utc":b.utc(cut),"full":{a.name:a.report() for a in full},
            "train":train_stats,"holdout":holdout_stats,"selected":selected,
            "stress_fee7_slip3":{a.name:a.report() for a in stress},
            "limitations":["OHLC-derived structural proxies; not live OKX replay or full CVD",
                           "nearest external target beyond confirmed M15 pivot; no RR-based target skipping",
                           "session windows Asia 02-08 Warsaw, London 08-10 London, NY 08-11 New York",
                           "limit after closed M5 retest, 15m expiry; conservative ambiguous fill handling",
                           "BE nominal entry after FTA or confirmed favorable M5 shift, costs included",
                           "fixed 3bp buffer; OB wick touch is not FVG full-fill; structural audit includes rejected setups",
                           "BB excluded from POI and FTA; shift CLOSE in a pre-existing active opposing zone blocks, overlapping limit waits for new setup",
                           "FTA recomputed at retest before placement; frozen TP and SL; post-placement FTA touch cancels pending, post-fill touch moves BE",
                           "fresh FTA only: first M5 wick overlap after confirmed creation retires zone from future FTA selection; first contact at shift retains veto, event-time snapshot prevents QM hindsight; entry POI unchanged",
                           "all ten original research variants; OF weak uses Binance taker delta proxy; IB market next open with opposite range boundary and RR recheck; no Sweep model in this configured suite"]}
    out=Path("risk-profile-output");out.mkdir(exist_ok=True)
    (out/"summary.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    (out/"trades.json").write_text(json.dumps({a.name:a.rows for a in full},indent=2,allow_nan=False)+"\n")
    (out/"structural-audit.json").write_text(json.dumps({a.name:a.audit for a in full},indent=2,allow_nan=False)+"\n")
    print("RISK_PROFILE_RESULT",json.dumps({k:v for k,v in report.items() if k not in ("archive_sha256",)},separators=(",",":")),flush=True)

if __name__=="__main__":main()
