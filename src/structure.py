#!/usr/bin/env python3
"""BTC candle structure observations from CLOSED Kraken Spot OHLC candles.

Events are descriptive only; no order placement or standalone trade signals.
Shift candidates require a break of confirmed swing against a prior trend.\nBOS candidates use the same confirmed pivots in continuation direction.\nNeither event is a verified ICT trade signal.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen
from src.strategy_models_v1 import scan_ifvg, scan_qm

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


def confirmed_pivots(bars, left=2, right=2):
    """Confirmed swing highs/lows; never use future or currently forming bars."""
    highs, lows = [], []
    if left < 1 or right < 1:
        raise ValueError("pivot strength must be positive")
    for i in range(left, len(bars) - right):
        window = bars[i-left:i+right+1]
        high = bars[i]["h"]
        low = bars[i]["l"]
        if all(high > row["h"] for j, row in enumerate(window) if j != left):
            highs.append({"index": i, "price": high, "time": bars[i]["t"]})
        if all(low < row["l"] for j, row in enumerate(window) if j != left):
            lows.append({"index": i, "price": low, "time": bars[i]["t"]})
    return highs, lows


def structural_shift(bars, left=2, right=2):
    """Early reversal: candle CLOSE breaks a confirmed swing against prior trend.

    Separate from BOS (continuation); confirmation is algorithmic and limited
    to this venue/timeframe, not discretionary ICT validation or a trade signal.
    """
    if len(bars) < max(8, 2*left + right + 3):
        return None
    highs, lows = confirmed_pivots(bars[:-1], left, right)
    if len(highs) < 2 or len(lows) < 2:
        return None
    prev, last = bars[-2], bars[-1]
    hh0, hh1 = highs[-2], highs[-1]
    ll0, ll1 = lows[-2], lows[-1]
    is_downtrend = hh1["price"] < hh0["price"] and ll1["price"] < ll0["price"]
    is_uptrend = hh1["price"] > hh0["price"] and ll1["price"] > ll0["price"]
    if is_downtrend and prev["c"] <= hh1["price"] < last["c"]:
        return {"kind": "bullish_shift_candidate", "break_level": hh1["price"],
                "broken_swing_utc": dt.datetime.fromtimestamp(hh1["time"], dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "confirmation": "closed_candle_above_confirmed_swing_high",
                "previous_structure": "lower_highs_lower_lows",
                "not_bos": True}
    if is_uptrend and prev["c"] >= ll1["price"] > last["c"]:
        return {"kind": "bearish_shift_candidate", "break_level": ll1["price"],
                "broken_swing_utc": dt.datetime.fromtimestamp(ll1["time"], dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "confirmation": "closed_candle_below_confirmed_swing_low",
                "previous_structure": "higher_highs_higher_lows",
                "not_bos": True}
    return None

def continuation_bos(bars, left=2, right=2):
    """Candidate continuation BOS using last CLOSE and confirmed pivot structure.

    Require two successive higher swing highs AND higher swing lows for bullish
    continuation, or lower highs AND lower lows for bearish continuation.
    A BOS may not be inferred from a wick piercing the level.
    """
    if len(bars) < max(8, 2*left + right + 3):
        return None
    highs, lows = confirmed_pivots(bars[:-1], left, right)
    if len(highs) < 2 or len(lows) < 2:
        return None
    high0, high1 = highs[-2:]
    low0, low1 = lows[-2:]
    prev, last = bars[-2:]
    rising = high1["price"] > high0["price"] and low1["price"] > low0["price"]
    falling = high1["price"] < high0["price"] and low1["price"] < low0["price"]
    if rising and prev["c"] <= high1["price"] < last["c"]:
        return {"kind": "bullish_bos_candidate",
                "break_level": high1["price"],
                "broken_swing_utc": dt.datetime.fromtimestamp(high1["time"], dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "confirmation": "closed_candle_above_confirmed_swing_high",
                "previous_structure": "higher_highs_higher_lows",
                "not_shift": True}
    if falling and prev["c"] >= low1["price"] > last["c"]:
        return {"kind": "bearish_bos_candidate",
                "break_level": low1["price"],
                "broken_swing_utc": dt.datetime.fromtimestamp(low1["time"], dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "confirmation": "closed_candle_below_confirmed_swing_low",
                "previous_structure": "lower_highs_lower_lows",
                "not_shift": True}
    return None


def events_for(bars, timeframe):
    if len(bars) < 4:
        return {"status": "insufficient_candles", "events": [], "fvg": [], "latest_closed_utc": None}
    a, b = bars[-2], bars[-1]
    events = []
    shift = structural_shift(bars)
    if shift is not None:
        events.append(shift)
    bos = continuation_bos(bars)
    if bos is not None:
        events.append(bos)
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
    extra = ({"ifvg": scan_ifvg(bars)} if timeframe in ("H1", "H4", "D1", "W1") else
             {"qm": scan_qm(bars)} if timeframe in ("M5", "M15") else {})
    return {"status": "ok", "events": events, "fvg": active[-10:], **extra,
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
              "notes": ["Only closed OHLC candles", "Shift and BOS are separate candidate observations based on confirmed pivots and last closed candles; no validated trade signal",
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
