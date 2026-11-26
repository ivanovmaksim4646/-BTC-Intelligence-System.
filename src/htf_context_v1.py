#!/usr/bin/env python3
"""HTF context v1. Descriptive levels only; no trade levels or HTF directional score."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
DURATION = {"H1": 3600, "H4": 14400, "D1": 86400}
MAX_LAG = {"H1": 7200, "H4": 28800, "D1": 172800}

def as_utc(value):
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return t.astimezone(dt.timezone.utc) if t.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError):
        return None

def is_level(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and 0 < value < 10000000

def build(structure, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    output = {
        "schema_version": "1.0",
        "classification": "htf_observation_only",
        "generated_at_utc": now.isoformat(),
        "venue": structure.get("source"),
        "futures_chart_validated": False,
        "trade_signal": None,
        "notes": [
            "Kraken Spot HTF levels are not verified Binance/BingX perpetual levels.",
            "FVG observations do not establish unfilled or unmitigated status.",
            "No HTF directional bias, entry, stop, target or RR is inferred."
        ],
        "timeframes": {}
    }
    for tf, duration in DURATION.items():
        item = (structure.get("timeframes") or {}).get(tf) or {}
        start = as_utc(item.get("latest_closed_utc"))
        close_time = start + dt.timedelta(seconds=duration) if start else None
        fresh = (item.get("status") == "ok" and close_time is not None and
                 dt.timedelta(0) <= now - close_time <= dt.timedelta(seconds=MAX_LAG[tf]))
        if not fresh or not all(is_level(item.get(k)) for k in ("last_high", "last_low", "last_close")):
            output["timeframes"][tf] = {"status": "unavailable", "reason": "missing_or_stale_closed_candle"}
            continue
        if not item["last_low"] <= item["last_close"] <= item["last_high"]:
            output["timeframes"][tf] = {"status": "unavailable", "reason": "inconsistent_ohlc"}
            continue
        gaps = []
        for gap in item.get("fvg") or []:
            if gap.get("kind") not in ("bullish_fvg", "bearish_fvg"):
                continue
            lo, hi = gap.get("low"), gap.get("high")
            if not is_level(lo) or not is_level(hi) or lo >= hi:
                continue
            gaps.append({"kind": gap["kind"], "low": lo, "high": hi,
                         "formed_at": gap.get("formed_at"),
                         "mitigation_status": "unknown"})
        output["timeframes"][tf] = {
            "status": "observed",
            "last_closed_candle_start_utc": start.isoformat(),
            "last_high": item["last_high"],
            "last_low": item["last_low"],
            "last_close": item["last_close"],
            "events": [e for e in item.get("events") or [] if isinstance(e, dict)],
            "fvg": gaps,
            "futures_chart_validated": False,
        }
    return output

def main():
    try:
        structure = json.loads((DATA / "BTC-structure-current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        structure = {}
    result = build(structure)
    (DATA / "BTC-htf-context-v1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("HTF context:", {k: v["status"] for k,v in result["timeframes"].items()})

if __name__ == "__main__":
    main()
