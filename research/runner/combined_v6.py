"""Combined #6 diagnostic replay; all configured M15-confirmed candidates plus daily IB."""
import argparse,json
from pathlib import Path
from datetime import date
from collections import Counter
from research.baseline.dataset import stamp
from research.baseline.replay import stats
from research.runner import structure_v7,ranges_v6
from research.runner.inputs import verified_bars,verified_funding
from research.runner.portfolio_v6 import combine
from research.runner.charts import render

def run(start,end,out,cache):
    bars,pins=verified_bars(start,end,cache)
    lo,hi=stamp(start),stamp(end)
    funding=verified_funding(lo,hi)
    count=(hi-lo)//300
    def replay(policy):
        result=structure_v7.backtest(bars,funding,count,start=lo,end=hi,policy=policy)
        result.update(ranges_v6.run(bars,funding,count,start=lo,end=hi,fee=.0005,slip=.0002,policy=policy))
        return result
    books=replay("structural")
    comparison={}
    for policy in ("fixed","be","half","structural"):
        other=books if policy=="structural" else replay(policy)
        comparison[policy]={"models":{n:stats(book.rows) for n,book in other.items()},
                            "portfolio":combine(other)["summary"]}
    portfolio=combine(books)
    models={n:dict(**stats(book.rows),limit_events=dict(Counter(e["event"] for e in getattr(book,"limit_events",[]))),
                   rejections=dict(Counter(e["reason"] for e in book.rejected))) for n,book in books.items()}
    summary=dict(backtest=6,classification="diagnostic_not_full_strategy_acceptance",
                 start=str(start),end_exclusive=str(end),evaluation_m5=count,warmup_m5=len(bars)-count,
                 funding_settlements=len(funding),archive_sha256=pins,models=models,
                 portfolio=portfolio["summary"],management_comparison=comparison,limitations=["H4 range is a six-bar two-touch research proxy; not user validated",
                 "W1 uses Monday UTC and limited 30-day warmup", "Independent candidate projection, not shared live order state",
                 "No counterfactual cancellation PnL; BE excludes future funding",
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
