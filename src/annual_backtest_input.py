"""Verified archive input for independent research; not a strategy backtest."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
from src.binance_vision_archive import fetch_zip, parse_archive, url_for

def load_day(day):
    url=url_for("5m",day)
    for attempt in range(3):
        try:
            raw=fetch_zip(url)
            digest=fetch_zip(url+".CHECKSUM").decode("ascii").split()[0].lower()
            if hashlib.sha256(raw).hexdigest()!=digest:
                raise ValueError("archive checksum mismatch")
            bars=parse_archive(raw,"5m",day)
            start=int(dt.datetime.combine(day,dt.time.min,dt.timezone.utc).timestamp())
            if len(bars)!=288 or any(b["t"]!=start+i*300 for i,b in enumerate(bars)):
                raise ValueError("daily continuity failure")
            return bars
        except Exception:
            if attempt==2:raise

def main():
    start=dt.date(2025,11,27)
    end=dt.date(2026,11,27)
    warm=start-dt.timedelta(days=30)
    days=[warm+dt.timedelta(days=i) for i in range((end-warm).days)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        bars=[b for daybars in pool.map(load_day,days) for b in daybars]
    assert len(bars)==395*288
    out=Path("research-output")
    out.mkdir(exist_ok=True)
    (out/"candles.json").write_text(json.dumps(bars,separators=(",",":")))
    report={"source":"Binance USD-M BTCUSDT","start":str(start),"end_exclusive":str(end),"warmup_days":30,"test_bars":365*288,"all_bars":len(bars),"checksum_verified":True,"classification":"historical_ohlc_only","strategy_results":None}
    (out/"coverage.json").write_text(json.dumps(report,indent=2))
    print(report)
if __name__=="__main__":main()
