#!/usr/bin/env python3
"""Read-only validation of official Binance Vision USD-M futures daily archives.

This is an OFFLINE historical sample, not a realtime feed. Never use it as
current BTC signal input. Files fetched from Binance's public archive only.
"""
from __future__ import annotations
import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
try:
    from src.binance_futures_candles import parse_klines, INTERVALS
except ModuleNotFoundError:
    from binance_futures_candles import parse_klines, INTERVALS

ROOT=Path(__file__).resolve().parents[1]
BASE="https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT"
MAX_COMPRESSED_BYTES=12_000_000

def url_for(interval, date):
    if interval not in INTERVALS: raise ValueError("unsupported interval")
    if not isinstance(date, dt.date): raise ValueError("date must be date")
    stamp=date.isoformat()
    return f"{BASE}/{interval}/BTCUSDT-{interval}-{stamp}.zip"

def fetch_zip(url, opener=urlopen):
    req=Request(url,headers={"User-Agent":"BTC-Intelligence-Archive-Validator/1.0"})
    with opener(req,timeout=25) as resp:
        data=resp.read(MAX_COMPRESSED_BYTES+1)
    if len(data)>MAX_COMPRESSED_BYTES:raise ValueError("archive exceeds limit")
    return data

def parse_archive(data, interval, date):
    if interval not in INTERVALS:raise ValueError("unsupported interval")
    expected=f"BTCUSDT-{interval}-{date.isoformat()}.csv"
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        if bundle.namelist()!=[expected]:
            raise ValueError("archive path mismatch")
        info=bundle.getinfo(expected)
        if info.file_size>50_000_000:raise ValueError("uncompressed archive too large")
        with bundle.open(expected) as fh:
            rows=list(csv.reader(io.TextIOWrapper(fh,encoding="utf-8-sig")))
    prepared=[]
    for row in rows:
        if not row:continue
        if row[0].lower() in ("open_time","open time"):continue
        if len(row)<7:raise ValueError("missing csv columns")
        try:
            open_ms=int(row[0])
            close_ms=int(row[6])
            float(row[1]);float(row[2]);float(row[3]);float(row[4])
        except (ValueError,TypeError) as exc:
            raise ValueError("invalid futures CSV record") from exc
        prepared.append([open_ms]+row[1:6]+[close_ms])
    start=int(dt.datetime.combine(date,dt.time.min,dt.timezone.utc).timestamp())
    # Parse only fully closed archive intervals; weekly candles across
    # daily files cannot be considered complete inside one daily sample.
    if interval=="1w":raise ValueError("weekly cannot be validated from single-day archive")
    # parse_klines requires freshness relative to clock; supply synthetic
    # clock immediately after the FINAL closed sample, then independently
    # verify archive calendar boundaries.
    if not prepared:raise ValueError("empty archive")
    fake_now=int(prepared[-1][6])+1
    bars=parse_klines(prepared,INTERVALS[interval],fake_now)
    end=start+86400
    if any(not start<=b["t"]<end for b in bars):
        raise ValueError("archive contains candles outside requested UTC date")
    return bars

def probe(date, intervals=("5m","15m","1h","4h"), downloader=fetch_zip):
    # Preserve partial failures and accurate provenance.
    out={"schema_version":"1.0","classification":"historical_research_only",
         "source":"Binance Vision USD-M BTCUSDT perpetual archive",
         "day":date.isoformat(),"not_live_data":True,"status":"partial",
         "timeframes":{},"errors":{},"trade_signal":None}
    for tf in intervals:
        try:
            bars=parse_archive(downloader(url_for(tf,date)),tf,date)
            out["timeframes"][tf]={"status":"verified","count":len(bars),
                                    "first_open_utc":dt.datetime.fromtimestamp(bars[0]["t"],dt.timezone.utc).isoformat(),
                                    "last_open_utc":dt.datetime.fromtimestamp(bars[-1]["t"],dt.timezone.utc).isoformat()}
        except (HTTPError,URLError,OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
            out["timeframes"][tf]={"status":"unavailable"}
            out["errors"][tf]=type(exc).__name__
    if out["timeframes"] and all(v["status"]=="verified" for v in out["timeframes"].values()):
        out["status"]="verified_historical"
    return out

def main():
    # Fixed historical date; never infer that archives are published for today.
    sample=dt.date(2026,11,20)
    result=probe(sample)
    dest=ROOT/"data"/"BTC-binance-vision-archive-probe.json"
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))
    if result["status"]!="verified_historical":
        raise SystemExit("At least one historical interval is unavailable")

if __name__=="__main__":
    main()
