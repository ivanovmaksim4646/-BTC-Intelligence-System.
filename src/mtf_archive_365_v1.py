"""365-day Binance Futures archive coverage check; no strategy performance claims."""
import concurrent.futures as cf
import datetime as dt
import json
from pathlib import Path
from src.binance_vision_archive import fetch_zip, parse_archive, url_for

START=dt.date(2025,11,27)
END=dt.date(2026,11,27)
WARMUP=30

def day(date):
    for attempt in range(3):
        try:
            bars=parse_archive(fetch_zip(url_for("5m",date)),"5m",date)
            expected=int(dt.datetime.combine(date,dt.time.min,dt.timezone.utc).timestamp())
            if len(bars)!=288 or any(b["t"]!=expected+300*i for i,b in enumerate(bars)):
                raise ValueError("incomplete daily archive")
            return date.isoformat(),bars,None
        except Exception as exc:
            error=type(exc).__name__+": "+str(exc)[:160]
    return date.isoformat(),[],error

def main():
    first=START-dt.timedelta(days=WARMUP)
    dates=[first+dt.timedelta(days=i) for i in range((END-first).days)]
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(day,dates))
    errors={d:e for d,b,e in results if e}
    bars=[b for d,rows,e in results for b in rows]
    report={"source":"Binance Vision USD-M BTCUSDT futures","start":START.isoformat(),"end_exclusive":END.isoformat(),"warmup_days":WARMUP,"requested_days":len(dates),"verified_days":len(dates)-len(errors),"errors":errors,"bars":len(bars),"status":"complete" if not errors else "incomplete","performance_verified":False}
    dest=Path("data")
    dest.mkdir(exist_ok=True)
    (dest/"BTC-mtf-365-coverage.json").write_text(json.dumps(report,indent=2))
    if not errors:
        (dest/"BTC-mtf-365-m5.json").write_text(json.dumps(bars,separators=(",",":")))
    print(json.dumps(report))
    if errors:raise SystemExit("Full coverage required")
if __name__=="__main__":main()
