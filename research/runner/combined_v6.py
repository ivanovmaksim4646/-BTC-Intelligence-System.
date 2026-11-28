"""Combined #6 diagnostic replay; all configured M15-confirmed candidates plus daily IB."""
import argparse,json
from pathlib import Path
from datetime import date
from collections import Counter
from research.baseline.dataset import stamp
from research.baseline.replay import stats
from research.runner import structure_v7,deviation_replay
from research.runner.inputs import verified_bars,verified_funding
from research.runner.portfolio_v6 import combine
from research.runner.charts import render

def run(start,end,out,cache):
    bars,pins=verified_bars(start,end,cache)
    lo,hi=stamp(start),stamp(end)
    funding=verified_funding(lo,hi)
    count=(hi-lo)//300
    books=structure_v7.backtest(bars,funding,count,start=lo,end=hi)
    books.update(deviation_replay.run(bars,funding,count,start=lo,end=hi,fee=.0005,slip=.0002))
    portfolio=combine(books)
    models={n:dict(**stats(book.rows),limit_events=dict(Counter(e["event"] for e in getattr(book,"limit_events",[]))),
                   rejections=dict(Counter(e["reason"] for e in book.rejected))) for n,book in books.items()}
    summary=dict(backtest=6,classification="diagnostic_not_full_strategy_acceptance",
                 start=str(start),end_exclusive=str(end),evaluation_m5=count,warmup_m5=len(bars)-count,
                 funding_settlements=len(funding),archive_sha256=pins,models=models,
                 portfolio=portfolio["summary"],limitations=["Daily IB only; H4/W1 IB and general range not integrated",
                 "IB market-only", "Independent candidate projection, not shared live order state",
                 "No counterfactual cancellation PnL or separate management policies",
                 "No verified user example recognition"])
    out.mkdir(parents=True,exist_ok=True)
    for name,obj in (("summary",summary),("portfolio",portfolio),("trades",[r for book in books.values() for r in book.rows]),
                     ("limit-events",{n:getattr(book,"limit_events",[]) for n,book in books.items()})):
        (out/(name+".json")).write_text(json.dumps(obj,indent=2,allow_nan=False))
    render(out/"entries.html",bars,[r for book in books.values() for r in book.rows])
    print(json.dumps(summary,indent=2,allow_nan=False))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--start",type=date.fromisoformat,default=date(2025,11,27))
    p.add_argument("--end",type=date.fromisoformat,default=date(2025,12,4))
    p.add_argument("--out",type=Path,default=Path("research-output"))
    p.add_argument("--cache",type=Path,default=Path(".research-cache"))
    a=p.parse_args()
    run(a.start,a.end,a.out,a.cache)
