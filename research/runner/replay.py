"""Configurable, historical research replay. Writes only the specified output directory."""
import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from research.baseline import replay
from research.baseline.dataset import START, END, stamp
from research.runner.charts import render
from research.runner.validation import SPEC, assess
from research.runner.inputs import BASE, FUNDING_SHA, verified_bars, verified_funding

CONFIG = Path(__file__).with_name("config.json")
FIELDS = {"start_utc","end_exclusive_utc","models","fee_bps_per_side","slippage_bps_per_side"}


def parameters(cfg):
    if set(cfg) != FIELDS:
        raise ValueError(f"Expected config keys {sorted(FIELDS)}")
    start = date.fromisoformat(cfg["start_utc"])
    end = date.fromisoformat(cfg["end_exclusive_utc"])
    if not START <= start < end <= END:
        raise ValueError(f"Choose UTC dates within [{START}, {END}]")
    models = cfg["models"]
    if not isinstance(models,list) or not models or any(n not in replay.MODELS for n in models) or len(set(models)) != len(models):
        raise ValueError("Unknown, repeated or missing research model")
    costs = [cfg[k] for k in ("fee_bps_per_side","slippage_bps_per_side")]
    if any(type(v) not in (float,int) or not math.isfinite(v) or not 0 <= v <= 100 for v in costs):
        raise ValueError("Costs must be finite basis points in [0, 100]")
    return start, end, models, [v/10000 for v in costs]


def groups(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return {k: replay.stats(v) for k,v in sorted(grouped.items())}


def session(row):
    hour = datetime.fromisoformat(row["entry_utc"]).astimezone(replay.PL).hour
    for name, lo, hi in (("Asia",2,8),("London",9,11),("NY",14,17)):
        if lo <= hour < hi:
            return name
    return "outside_reference_windows"


def parity(start, end, costs, books):
    if start != START or costs != [replay.FEE, replay.SLIP]:
        return {"status":"not_applicable"}
    old = set(books).intersection(replay.BASE_MODELS)
    if not old:
        return {"status":"not_applicable"}
    with (BASE / "trades.csv").open() as fd:
        reference = [r for r in csv.DictReader(fd) if r["model"] in old and
                     datetime.fromisoformat(r["exit_utc"]).timestamp() <= stamp(end)]
    actual = [r for name in old for r in books[name].rows if r["outcome"] != "period_end" or end == END]
    def signature(r):
        return (r["model"],int(r["d"]),r["entry_utc"],r["exit_utc"],r["outcome"],
                *(float(r[k]) for k in ("entry","exit","stop","target","qty","R")))
    if sorted(map(signature,reference)) != sorted(map(signature,actual)):
        raise ValueError("Closed trades differ from the archived baseline")
    return {"status":"matched","closed_trades":len(reference),"models":sorted(old)}


def write_csv(path, fields, rows):
    with path.open("w",newline="") as fd:
        writer = csv.DictWriter(fd,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(cfg, cache, out):
    start,end,models,costs = parameters(cfg)
    bars,pins = verified_bars(start,end,cache)
    funding = verified_funding(stamp(start),stamp(end))
    expected = (end-start).days*288
    books = replay.backtest(bars,funding,expected,models=models,start=stamp(start),
                            end=stamp(end),fee=costs[0],slip=costs[1])
    reference = parity(start,end,costs,books)
    stats = {}
    trades, rejected = [], []
    for name,book in books.items():
        stats[name] = dict(**replay.stats(book.rows),drawdown_m5_pct=100*book.mtm_dd,
            long=replay.stats([t for t in book.rows if t["d"]==1]),
            short=replay.stats([t for t in book.rows if t["d"]==-1]),
            by_poi=groups(book.rows,lambda r:r["poi"]),by_session=groups(book.rows,session),
            rejected_setups=dict(Counter(e["reason"] for e in book.rejected)))
        trades.extend(book.rows)
        rejected.extend(book.rejected)
    summary = dict(classification="historical_research_only",instrument="Binance USD-M BTCUSDT",
        config=cfg,warmup_m5=len(bars)-expected,evaluation_m5=expected,funding_settlements=len(funding),
        archive_sha256=pins,funding_sha256=FUNDING_SHA,prefix_parity=reference,models=stats)
    out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
    (out/"entry-evidence.json").write_text(json.dumps(trades,indent=2,allow_nan=False)+"\n")
    with (BASE/"trades.csv").open() as fd:
        fields=next(csv.reader(fd))
    write_csv(out/"trades.csv",fields,trades)
    write_csv(out/"rejections.csv",["model","time_utc","reason","setup_utc","d"],rejected)
    write_csv(out/"equity.csv",["model","exit_utc","equity","R"],trades)
    validation=assess(bars,funding,stamp(start),stamp(end),models,costs,trades,json.loads(SPEC.read_text()))
    (out/"validation.json").write_text(json.dumps(validation,indent=2,allow_nan=False)+"\n")
    render(out/"entries.html",bars,trades)
    return summary


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",type=Path,default=CONFIG)
    p.add_argument("--cache",type=Path,default=Path(".research-cache"))
    p.add_argument("--out",type=Path,default=Path("research-output"))
    args=p.parse_args()
    s=run(json.loads(args.config.read_text()),args.cache,args.out)
    print(json.dumps({k:s[k] for k in ("evaluation_m5","warmup_m5","funding_settlements","prefix_parity")}))
