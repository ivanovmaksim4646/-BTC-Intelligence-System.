#!/usr/bin/env python3
"""BTC candle structure observations from CLOSED Kraken Spot OHLC candles.

Events are descriptive only; no order placement or standalone trade signals.
Swing BOS is intentionally NOT claimed: pivot confirmation and HTF context
must be defined and separately validated before signalling trades.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "BTC-structure-current.json"
INTERVALS = {"M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440, "W1": 10080}
MAX_CANDLE_AGE = {"M5": 600, "M15": 1800, "H1": 7200,
                  "H4": 28800, "D1": 172800, "W1": 1209600}

def candle(row):
    t, o, h, l, c = int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])
    if not all(math.isfinite(v) for v in (o, h, l, c)) or l > min(o, c) or h < max(o, c):
        raise ValueError("invalid OHLC candle")
    return {"t": t, "o": o, "h": h, "l": l, "c": c}

def closed_candles(rows, now_epoch, minutes):
    length = minutes * 60
    # Kraken's last OHLC entry can be the currently forming candle.
    unique = {item["t"]: item for item in map(candle, rows)
              if item["t"] + length <= now_epoch}
    return [unique[k] for k in sorted(unique)]

def events_for(bars, timeframe):
    if len(bars) < 4:
        return {"status": "insufficient_candles", "events": [], "fvg": [], "latest_closed_utc": None}
    a, b = bars[-2], bars[-1]
    prev, first = bars[-2], bars[-3]
    events = []
    # The candle preceding the last candle is the reference range.
    if b["h"] < a["h"] and b["l"] > a["l"]:
        events.append({"kind": "inside_bar", "reference_high": a["h"], "reference_low": a["l"]})
    if b["h"] > a["h"] and b["c"] < a["h"]:
        events.append({"kind": "sweep_high_reclaim_inside", "reference_high": a["h"]})
    if b["l"] < a["l"] and b["c"] > a["l"]:
        events.append({"kind": "sweep_low_reclaim_inside", "reference_low": a["l"]})
    # 3-candle imbalance: candle 1 high/low separated from candle 3 low/high.
    gaps = []
    for i in range(max(2, len(bars)-80), len(bars)):
        x, z = bars[i-2], bars[i]
        if z["l"] > x["h"]:
            gaps.append({"kind": "bullish_fvg", "low": x["h"], "high": z["l"],
                         "formed_at": z["t"]})
        if z["h"] < x["l"]:
            gaps.append({"kind": "bearish_fvg", "low": z["h"], "high": x["l"],
                         "formed_at": z["t"]})
    # Retain only gaps not completely traded through after formation.
    active = []
    for gap in gaps:
        later = [item for item in bars if item["t"] > gap["formed_at"]]
        filled = (any(item["l"] <= gap["low"] for item in later) if gap["kind"] == "bullish_fvg"
                  else any(item["h"] >= gap["high"] for item in later))
        if not filled:
            active.append(gap)
    return {"status": "ok", "events": events, "fvg": active[-10:],
            "latest_closed_utc": dt.datetime.fromtimestamp(b["t"], dt.timezone.utc).isoformat().replace("+00:00","Z"),
            "last_close": b["c"], "last_high": b["h"], "last_low": b["l"]}

def fetch_ohlc(minutes):
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=" + str(minutes)
    with urlopen(Request(url, headers={"User-Agent": "btc-intelligence-structure/1.0"}), timeout=25) as response:
        body = json.load(response)
    if body.get("error"):
        raise RuntimeError("Kraken OHLC error: " + str(body["error"]))
    result = body["result"]
    return next(value for key, value in result.items() if key != "last")

def build(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    epoch = now.timestamp()
    result = {"schema_version": "1.0", "source": "Kraken Spot XBTUSD",
              "collected_at_utc": now.isoformat().replace("+00:00","Z"),
              "classification": "structure_observation_only", "trade_signal": None,
              "notes": ["Only closed OHLC candles", "No confirmed BOS/Shift without verified swing structure",
                        "FVG is an algorithmic 3-candle imbalance, not automatically an institutional POI",
                        "Kraken Spot structures need independent validation on the intended futures chart"],
              "timeframes": {}}
    for timeframe, minutes in INTERVALS.items():
        try:
            bars = closed_candles(fetch_ohlc(minutes), epoch, minutes)
            record = events_for(bars, timeframe)
            if bars:
                end = bars[-1]["t"] + minutes*60
                if epoch - end > MAX_CANDLE_AGE[timeframe]:
                    record = {"status": "stale", "events": [], "fvg": [], "latest_closed_utc": None}
            result["timeframes"][timeframe] = record
        except (OSError, ValueError, KeyError, RuntimeError, TimeoutError) as exc:
            result["timeframes"][timeframe] = {"status": "unavailable", "events": [], "fvg": [],
                                               "error": type(exc).__name__}
    return result

def main():
    report = build()
    if all(v["status"] != "ok" for v in report["timeframes"].values()):
        raise RuntimeError("No verified structure data; withholding output")
    OUT.parent.mkdir(exist_ok=True, parents=True)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    tmp.replace(OUT)
    print("Structure observations written; no trading signal asserted")

if __name__ == "__main__":
    main()
