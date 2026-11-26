#!/usr/bin/env python3
"""Fail-closed, read-only BTC Signal Engine v1: watch classification, never trade advice.

Only a fresh, completed Kraken spot/futures watch candidate PLUS a matching,
fresh TradingView v2 M5 structural alert can produce LONG_WATCH / SHORT_WATCH.
No entry/stop/target/RR can be computed from the present feeds.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MAX_AGE = dt.timedelta(minutes=15)
DIRECTIONS = {
    "m5_bullish_bos": "long",
    "m5_bullish_shift": "long",
    "m5_bearish_bos": "short",
    "m5_bearish_shift": "short",
}

def parsedate(s):
    if not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t.astimezone(dt.timezone.utc) if t.tzinfo else None
    except ValueError:
        return None

def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

def read_events(path):
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError):
        return []

def evaluate(report, candidates, events, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    reasons = []
    result = {
        "schema_version": "1.0",
        "classification": "research_watch_only",
        "generated_at_utc": now.isoformat(),
        "decision": "NO_TRADE",
        "entry_signal": False,
        "trade_signal": None,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "rr": None,
        "probability": None,
        "matched_event": None,
        "reasons": reasons,
    }
    collected = parsedate(report.get("collected_at_utc"))
    if (report.get("report_data_status") != "ready" or
        not collected or not dt.timedelta(0) <= now - collected <= MAX_AGE):
        reasons.append("report_not_ready_or_stale")
        return result

    observations = candidates.get("timeframes") or {}
    m5 = observations.get("M5") or {}
    if m5.get("status") != "watch_candidate":
        reasons.append("no_confirmed_m5_watch_candidate")
        return result

    direction = m5.get("direction")
    if direction not in ("long", "short"):
        reasons.append("missing_candidate_direction")
        return result

    flow = (report.get("order_flow") or {}).get("M5") or {}
    cover = flow.get("coverage") or {}
    if (cover.get("spot") != "complete" or cover.get("futures") != "complete" or
        not isinstance(flow.get("spot_delta"), (int, float)) or
        not isinstance(flow.get("futures_delta"), (int, float))):
        reasons.append("incomplete_m5_venues")
        return result

    if not ((flow["spot_delta"] > 0 and flow["futures_delta"] > 0) if direction == "long"
            else (flow["spot_delta"] < 0 and flow["futures_delta"] < 0)):
        reasons.append("order_flow_not_directionally_aligned")
        return result

    matching = []
    for event in events:
        if event.get("source") != "btc-intelligence-tv-v2":
            continue
        if DIRECTIONS.get(event.get("event")) != direction or str(event.get("timeframe")) != "5":
            continue
        try:
            when = dt.datetime.fromtimestamp(event["time_ms"] / 1000, tz=dt.timezone.utc)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        if dt.timedelta(0) <= now - when <= MAX_AGE:
            matching.append((when, event))
    if not matching:
        reasons.append("no_fresh_matching_tradingview_v2_structure_event")
        return result

    _, event = max(matching, key=lambda item: item[0])
    result["decision"] = "LONG_WATCH" if direction == "long" else "SHORT_WATCH"
    result["matched_event"] = {"event": event["event"], "symbol": event.get("symbol"),
                               "time_ms": event["time_ms"]}
    reasons.extend(["watch_only_not_entry", "futures_chart_poi_sl_tp_rr_not_validated",
                    "kraken_and_tradingview_cross_venue_limitations"])
    return result

def main():
    report = read_json(DATA / "BTC-report-feed.json")
    candidates = read_json(DATA / "BTC-setup-candidates.json")
    events = read_events(DATA / "BTC-tradingview-events.jsonl")
    output = evaluate(report, candidates, events)
    confluence = read_json(DATA / "BTC-setup-confluence-v1.json")
    output["confluence"] = {
        "classification": confluence.get("classification", "unavailable"),
        "decision": confluence.get("decision", "NO_TRADE"),
        "models": {name: (model or {}).get("status", "unavailable")
                   for name, model in (confluence.get("models") or {}).items()},
        "note": "Research context only; confluence never authorizes trade entries.",
    }
    (DATA / "BTC-signal-engine-v1.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Signal Engine v1:", output["decision"], "(research only)")

if __name__ == "__main__":
    main()
