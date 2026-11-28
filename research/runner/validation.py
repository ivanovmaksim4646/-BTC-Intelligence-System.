"""Predeclared research folds. State and equity restart at each boundary."""
import math
from bisect import bisect_left
from datetime import datetime
from pathlib import Path
from research.baseline import replay

DAY = 86400
SPEC = Path(__file__).with_name("validation.json")


def bounds(start,end,train,test):
    if not all(type(x) is int and x>0 for x in (train,test)):
        raise ValueError("Fold lengths must be positive integer days")
    pos = start + train*DAY
    folds = []
    while pos < end:
        until=min(end,pos+test*DAY)
        folds.append((pos-train*DAY,pos,until))
        pos=until
    if not folds or len(folds)>12:
        raise ValueError("Choose one to twelve chronological validation folds")
    return folds


def approved_examples(examples, trades, models, start, end):
    keys = set()
    reports = []
    for ex in examples:
        if set(ex) != {"id","model","entry_utc","direction","expected","provenance"}:
            raise ValueError("Reference example must identify expected decision and provenance")
        key=ex["id"]
        dt=datetime.fromisoformat(ex["entry_utc"])
        if (not isinstance(key,str) or not key.strip() or key in keys or not ex["provenance"].strip()
            or dt.tzinfo is None or dt.utcoffset().total_seconds()!=0 or dt.timestamp()%300
            or ex["direction"] not in ("LONG","SHORT") or ex["expected"] not in ("entry","skip")
            or ex["model"] not in replay.MODELS):
            raise ValueError("Invalid or duplicate reference example")
        keys.add(key)
        t=int(dt.timestamp())
        if not start<=t<end or ex["model"] not in models:
            reports.append({"id":key,"status":"outside_config"});continue
        direction=1 if ex["direction"]=="LONG" else -1
        found=any(r["model"]==ex["model"] and r["d"]==direction and
                  datetime.fromisoformat(r["entry_utc"]).timestamp()==t for r in trades)
        reports.append({"id":key,"provenance":ex["provenance"],"status":
                        "match" if found==(ex["expected"]=="entry") else "mismatch"})
    return reports


def assess(bars, funding, start, end, models, costs, trades, spec):
    examples = approved_examples(spec["approved_examples"],trades,models,start,end)
    result={"approved_examples":examples,"recognition":"unvalidated" if not examples else
            ("mismatch" if any(e["status"]=="mismatch" for e in examples) else
             "matched_reviewed_examples" if any(e["status"]=="match" for e in examples) else "no_examples_in_window")}
    times=[b.t for b in bars]
    def window(lo,hi,names,charges):
        sub=bars[bisect_left(times,lo-30*DAY):bisect_left(times,hi)]
        if not sub or sub[0].t!=lo-30*DAY or sub[-1].t!=hi-300:
            raise ValueError("Fold coverage is incomplete")
        return replay.backtest(sub,funding,(hi-lo)//300,models=names,start=lo,end=hi,
                               fee=charges[0],slip=charges[1])
    fold=spec.get("walk_forward")
    if fold and end-start<2*DAY:
        result["walk_forward_skipped"]="At least two evaluation days required"
    elif fold:
        days=(end-start)//DAY
        ratios=[fold["train_fraction"],fold["test_fraction"]]
        if any(type(v) not in (float,int) or not 0<v<1 for v in ratios):
            raise ValueError("Fold fractions must lie between zero and one")
        train_days,test_days=[max(1,int(days*v)) for v in ratios]
        minimum=fold["min_training_trades"]
        if type(minimum) is not int or minimum<1:
            raise ValueError("Minimum training trades must be positive")
        result["walk_forward"]=[]
        for lo,cut,hi in bounds(start,end,train_days,test_days):
            train=window(lo,cut,models,costs)
            train_stats={name:replay.stats(book.rows) for name,book in train.items()}
            eligible=[name for name in models if train_stats[name]["n"]>=minimum]
            winner=max(eligible,key=lambda n:train_stats[n]["expect"],default=None)
            # Freeze selection on training data before replaying any holdout bars.
            test=window(cut,hi,models,costs)
            oos={name:replay.stats(book.rows) for name,book in test.items()}
            result["walk_forward"].append(dict(train_utc=[replay.utc(lo),replay.utc(cut)],
                test_utc=[replay.utc(cut),replay.utc(hi)],training=train_stats,
                selected_before_test=winner,holdout_all=oos,selected_holdout=oos.get(winner)))
    result["cost_sensitivity"]=[]
    scenarios=spec.get("cost_scenarios_bps",[])
    if len(scenarios)>3:
        raise ValueError("Maximum three prespecified cost scenarios")
    for pair in scenarios:
        if (not isinstance(pair,list) or len(pair)!=2 or
            any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for v in pair)):
            raise ValueError("Cost scenario requires fee and slippage bps")
        comparison=window(start,end,models,[v/10000 for v in pair])
        result["cost_sensitivity"].append(dict(fee_bps=pair[0],slippage_bps=pair[1],
            models={k:replay.stats(b.rows) for k,b in comparison.items()}))
    return result
