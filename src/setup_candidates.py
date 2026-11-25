#!/usr/bin/env python3
"""Conservative, non-executable BTC structure + order-flow candidate observations.

Sweep is OPTIONAL. Neither a structure candidate nor directional Delta alone is
an entry signal. The report intentionally has trade_signal=null.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "data" / "BTC-structure-current.json"
FLOW = ROOT / "data" / "BTC-analysis-current.json"
OUTPUT = ROOT / "data" / "BTC-setup-candidates.json"
TIMEFRAMES = ("M5", "M15", "H1")
STRUCTURE_KINDS = {
    "bullish_shift_candidate": "long",
    "bullish_bos_candidate": "long",
    "bearish_shift_candidate": "short",
    "bearish_bos_candidate": "short",
}
SWEEP_BONUS = {
    "long": "sweep_low_reclaim_inside",
    "short": "sweep_high_reclaim_inside",
}
MAX_AGE = {"M5": 900, "M15": 1800, "H1": 7200}
DURATION = {"M5": 300, "M15": 900, "H1": 3600}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp must have timezone")
    return parsed.astimezone(dt.timezone.utc)


def candidate_for(tf, structure, flow, now):
    if structure.get("status") != "ok" or not flow.get("complete") or not flow.get("aligned"):
        return {"status": "unavailable", "reason": "missing_complete_or_aligned_data"}
    if flow.get("observation") == "unavailable":
        return {"status": "unavailable", "reason": "order_flow_unavailable"}
    try:
        start = timestamp(structure["latest_closed_utc"])
        end = timestamp(flow["window_end_utc"])
    except (KeyError, ValueError, TypeError):
        return {"status": "unavailable", "reason": "invalid_candle_time"}
    # Structure records the candle START time; flow window_end is the CLOSE time.
    if abs((start + dt.timedelta(seconds=DURATION[tf]) - end).total_seconds()) > 1:
        return {"status": "unavailable", "reason": "structure_flow_time_mismatch"}
    age = (now-end).total_seconds()
    if age < -60 or age > MAX_AGE[tf]:
        return {"status": "unavailable", "reason": "stale_candles"}
    events = structure.get("events", [])
    breaks = [e for e in events if e.get("kind") in STRUCTURE_KINDS]
    if not breaks:
        return {"status": "no_structure_break", "reason": "no_confirmed_close_break"}
    chosen = breaks[0]
    direction = STRUCTURE_KINDS[chosen["kind"]]
    spot = flow.get("spot_pressure")
    futures = flow.get("futures_pressure")
    if not isinstance(spot, (float, int)) or not isinstance(futures, (float, int)):
        return {"status": "unavailable", "reason": "missing_pressure"}
    sign = 1 if direction == "long" else -1
    spot_supports = sign*spot > 0.1
    futures_supports = sign*futures > 0.1
    sweep_present = any(e.get("kind") == SWEEP_BONUS[direction] for e in events)
    return {
        "status": "watch_candidate" if spot_supports and futures_supports else "unconfirmed",
        "direction": direction,
        "structure": chosen["kind"],
        "break_level": chosen["break_level"],
        "spot_pressure": spot, "futures_pressure": futures,
        "spot_supports": spot_supports, "futures_supports": futures_supports,
        "sweep_bonus": sweep_present,
        "reason": "structure_and_both_venue_pressures_align" if spot_supports and futures_supports
                  else "structure_break_without_both_venue_pressure_confirmation",
        "entry_signal": False,
    }


def evaluate(structure_report, flow_report, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must have timezone")
    output = {
        "schema_version": "1.0",
        "evaluated_at_utc": now.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "classification": "watchlist_only",
        "trade_signal": None,
        "notes": [
            "Sweep is optional and cannot independently trigger a candidate.",
            "Candidate requires completed aligned Kraken Spot and Futures pressure and a close-confirmed structural break.",
            "No validated futures-chart POI, displacement, stop, target, RR, or performance testing: never auto-trade.",
            "Absolute CVD is unavailable; window Delta and Delta-CVD change are the same measurement.",
        ],
        "timeframes": {},
    }
    for tf in TIMEFRAMES:
        if not flow_report.get("fresh"):
            output["timeframes"][tf] = {"status": "unavailable", "reason": "stale_order_flow_snapshot"}
        else:
            output["timeframes"][tf] = candidate_for(
                tf,
                (structure_report.get("timeframes") or {}).get(tf) or {},
                (flow_report.get("timeframes") or {}).get(tf) or {},
                now,
            )
    return output


def main():
    structure = json.loads(STRUCTURE.read_text(encoding="utf-8"))
    flow = json.loads(FLOW.read_text(encoding="utf-8"))
    report = evaluate(structure, flow)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    temp.replace(OUTPUT)
    print("BTC watchlist candidate observations updated (not trade signals)")


if __name__ == "__main__":
    main()
