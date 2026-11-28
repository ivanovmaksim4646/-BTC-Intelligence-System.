"""Read only pinned historical Binance USD-M archives and actual funding settlements."""
import csv
import hashlib
import io
import json
import math
import os
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from urllib.error import URLError

from research.baseline.dataset import stamp
from research.baseline.replay import Bar
from src.binance_vision_archive import fetch_zip

BASE = Path(__file__).resolve().parents[1] / "baseline"
CHECKSUMS = BASE / "checksums.json"
FUNDING_SHA = "145c168c9926e76aad759ef43d9bb92d5535f7ef57e3cef4414cb86b9d913f57"


def archive_keys(begin, end, manifest):
    day = begin
    keys = []
    while day < end:
        month = day.strftime("%Y-%m")
        if month in manifest:
            keys.append(month)
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        elif day.isoformat() in manifest:
            keys.append(day.isoformat())
            day += timedelta(days=1)
        else:
            raise ValueError(f"Missing pinned archive for {day}")
    return keys


def archive_bytes(key, digest, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{key}-{digest}.zip"
    if path.exists():
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() == digest:
            return raw
    period = "monthly" if len(key) == 7 else "daily"
    name = f"BTCUSDT-5m-{key}.zip"
    url = f"https://data.binance.vision/data/futures/um/{period}/klines/BTCUSDT/5m/{name}"
    for attempt in range(3):
        try:
            raw = fetch_zip(url)
            break
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"Archive checksum mismatch for {key}")
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return raw


def parse_bars(raw, key, begin, end):
    name = f"BTCUSDT-5m-{key}.csv"
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        if bundle.namelist() != [name] or bundle.getinfo(name).file_size > 50_000_000:
            raise ValueError(f"Unexpected archive member for {key}")
        with bundle.open(name) as fd:
            for r in csv.reader(io.TextIOWrapper(fd, encoding="utf-8-sig")):
                if r and r[0].lower() == "open_time":
                    continue
                ms = int(r[0])
                if not begin*1000 <= ms < end*1000:
                    continue
                if ms % 300000 or int(r[6]) != ms + 299999:
                    raise ValueError(f"Invalid M5 bounds at {ms}")
                b = Bar(ms//1000, *(float(r[i]) for i in (1,2,3,4,5,9)))
                if (not all(math.isfinite(v) for v in b) or not 0 < b.l <= min(b.o,b.c)
                        <= max(b.o,b.c) <= b.h or not 0 <= b.buy <= b.v):
                    raise ValueError(f"Invalid OHLC or taker volume at {b.t}")
                yield b


def verified_bars(start, end, cache):
    first = start - timedelta(days=30)
    begin_ts, end_ts = stamp(first), stamp(end)
    manifest = json.loads(CHECKSUMS.read_text())
    keys = archive_keys(first, end, manifest)
    rows = []
    for key in keys:
        raw = archive_bytes(key, manifest[key], cache)
        rows.extend(parse_bars(raw, key, begin_ts, end_ts))
    if len(rows) != (end_ts-begin_ts)//300 or any(
            b.t != begin_ts+i*300 for i, b in enumerate(rows)):
        raise ValueError("Missing, out-of-order or duplicate M5 bar")
    return rows, {k: manifest[k] for k in keys}


def verified_funding(begin, end):
    raw = (BASE / "funding.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != FUNDING_SHA:
        raise ValueError("Pinned funding checksum mismatch")
    data = {int(k): v for k, v in json.loads(raw).items() if begin <= int(k) < end}
    if sorted(data) != list(range(begin, end, 28800)):
        raise ValueError("Missing or off-grid BTCUSDT funding settlement")
    if any(len(v) != 2 or not all(map(math.isfinite, v)) or v[1] <= 0 for v in data.values()):
        raise ValueError("Invalid funding rate or mark")
    return data
