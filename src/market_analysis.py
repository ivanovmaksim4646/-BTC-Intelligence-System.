#!/usr/bin/env python3
"""Conservative BTC order-flow observations. Never emit trade-entry signals."""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "data" / "BTC-intelligence-current.json"
OUTPUT = ROOT / "data" / "BTC-analysis-current.json"
TIMEFRAMES = ("M5", "M15", "H1", "H4")
MAX_AGE_SECONDS = 5400

def parse_utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.utcoffset() is None:
        raise ValueError("timestamp lacks timezone")
    return d.astimezone(dt.timezone.utc)

def finite_number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

def pressure(item):
    buy, sell = item.get("buy_volume"), item.get("sell_volume")
    if not finite_number(buy) or not finite_number(sell) or buy < 0 or sell < 0 or buy + sell == 0:
        return None
    return round((buy - sell) / (buy + sell), 4)

def analyse(snapshot, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    stamp = parse_utc(snapshot.get("collected_at_utc"))
    age = (now - stamp).total_seconds()
    max_age = min(int(snapshot.get("health", {}).get("freshness_limit_seconds", MAX_AGE_SECONDS)), MAX_AGE_SECONDS)
    fresh = -60 <= age <= max_age
    report = {
        "schema_version": "1.0",
        "data_collected_at_utc": snapshot.get("collected_at_utc"),
        "analysed_at_utc": now.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_age_seconds": round(age),
        "fresh": fresh,
        "classification": "observation_only",
        "trade_signal": None,
        "limitations": [
            "No M5/M15 price structure, BOS/Shift, POI or FVG verification in this dataset.",
            "Kraken Spot and Kraken Futures represent different market segments.",
            "Delta and change in CVD for one window are one confirmation, not two."
        ],
        "timeframes": {}
    }
    flows = snapshot.get("order_flow") or {}
    durations = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
    for tf in TIMEFRAMES:
        spot = (flows.get("spot") or {}).get(tf) or {}
        futures = (flows.get("futures") or {}).get(tf) or {}
        aligned = bool(spot.get("window_start_utc") and
                       spot.get("window_start_utc") == futures.get("window_start_utc") and
                       spot.get("window_end_utc") == futures.get("window_end_utc"))
        complete = aligned and spot.get("coverage") == futures.get("coverage") == "complete"
        item = {"window_end_utc": spot.get("window_end_utc") if aligned else None,
                "aligned": aligned, "complete": complete,
                "spot_delta": None, "futures_delta": None,
                "spot_pressure": None, "futures_pressure": None,
                "observation": "unavailable"}
        if fresh and complete:
            try:
                end = parse_utc(spot["window_end_utc"])
                secs = durations[tf]
                expected_end = now.astimezone(dt.timezone.utc).timestamp() // secs * secs
                current_bar = abs(end.timestamp() - expected_end) < 1
            except (ValueError, TypeError):
                current_bar = False
            sd, fd = spot.get("delta"), futures.get("delta")
            sp, fp = pressure(spot), pressure(futures)
            if current_bar and finite_number(sd) and finite_number(fd) and sp is not None and fp is not None:
                item.update(spot_delta=sd, futures_delta=fd, spot_pressure=sp, futures_pressure=fp)
                if sp > .1 and fp < -.1:
                    item["observation"] = "spot_buy_futures_sell_divergence"
                elif sp < -.1 and fp > .1:
                    item["observation"] = "spot_sell_futures_buy_divergence"
                elif sp > .1 and fp > .1:
                    item["observation"] = "both_aggressive_buy"
                elif sp < -.1 and fp < -.1:
                    item["observation"] = "both_aggressive_sell"
                else:
                    item["observation"] = "mixed_or_neutral"
        report["timeframes"][tf] = item
    oi = (snapshot.get("derivatives") or {}).get("open_interest") or {}
    h1change = (oi.get("change") or {}).get("H1")
    report["open_interest"] = {
        "venue": "Kraken Futures",
        "value": oi.get("value") if fresh and finite_number(oi.get("value")) else None,
        "h1_change": h1change if fresh and finite_number(h1change) else None
    }
    if not fresh:
        report["limitations"].append("Stale or future-dated snapshot; observations withheld.")
    return report

def main():
    report = analyse(json.loads(CURRENT.read_text(encoding="utf-8")))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(OUTPUT)
    print("BTC analysis written: " + report["classification"])

if __name__ == "__main__":
    main()
