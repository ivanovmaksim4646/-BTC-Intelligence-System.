#!/usr/bin/env python3
"""Local BTC system health: no external API calls, no trading signals.

Missing TradingView events do not by themselves prove a delivery failure.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "BTC-system-health.json"


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone.utc) if parsed.tzinfo is not None else None
    except ValueError:
        return None


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def component_age(record, field, now, max_age_seconds=900):
    if not isinstance(record, dict):
        return {"status": "missing_or_invalid", "age_seconds": None}
    instant = parse_time(record.get(field))
    if instant is None:
        return {"status": "missing_or_invalid", "age_seconds": None}
    age = (now - instant).total_seconds()
    if age < -90:
        return {"status": "invalid_future_timestamp", "age_seconds": round(age)}
    return {"status": "ok" if age <= max_age_seconds else "stale",
            "age_seconds": round(max(0, age))}


def evaluate(data_dir=DATA, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    now = now.astimezone(dt.timezone.utc)
    current = read_json(data_dir / "BTC-intelligence-current.json")
    analysis = read_json(data_dir / "BTC-analysis-current.json")
    structure = read_json(data_dir / "BTC-structure-current.json")
    candidates = read_json(data_dir / "BTC-setup-candidates.json")
    scheduler = read_json(data_dir / "BTC-scheduler-health.json")
    components = {
        "kraken_collection": component_age(current, "collected_at_utc", now),
        "order_flow_analysis": component_age(analysis, "analysed_at_utc", now),
        "structure_observation": component_age(structure, "collected_at_utc", now),
        "watchlist_evaluation": component_age(candidates, "evaluated_at_utc", now),
        "github_workflow_trigger": component_age(scheduler, "recorded_at_utc", now),
    }
    if isinstance(current, dict) and current.get("status") != "verified":
        components["kraken_collection"]["status"] = "unverified"
    if isinstance(analysis, dict) and not analysis.get("fresh"):
        components["order_flow_analysis"]["status"] = "unverified"
    if isinstance(scheduler, dict):
        components["github_workflow_trigger"].update({
            "event": scheduler.get("event"),
            "source": scheduler.get("source"),
            "slot": scheduler.get("slot"),
        })
    observed = (isinstance(scheduler, dict)
                and scheduler.get("event") == "workflow_dispatch"
                and scheduler.get("source") == "cloudflare")
    components["cloudflare_dispatch"] = {
        "status": ("last_dispatch_observed" if components["github_workflow_trigger"]["status"] == "ok"
                   else "last_dispatch_stale") if observed else "last_dispatch_unverified",
        "note": ("A recent Cloudflare-origin GitHub run was observed; this does not prove continuous uptime"
                 if observed else "A GitHub schedule event does not prove Cloudflare dispatch works"),
    }
    tv = {"status": "not_yet_verified", "events_saved": None,
          "note": "No saved events is not proof there were no TradingView alerts"}
    tv_path = data_dir / "BTC-tradingview-events.jsonl"
    try:
        if tv_path.exists():
            records = [json.loads(line) for line in tv_path.read_text(encoding="utf-8").splitlines()
                       if line.strip()]
            tv["events_saved"] = len(records)
            if records:
                tv["status"] = "event_history_present"
                tv["last_event_received_at_utc"] = records[-1].get("received_at_utc")
    except (OSError, ValueError, UnicodeError):
        tv["status"] = "invalid_history"
    components["tradingview_intake"] = tv
    core = ("kraken_collection", "order_flow_analysis", "structure_observation",
            "watchlist_evaluation", "github_workflow_trigger")
    flow = read_json(data_dir / "BTC-okx-reconciled-flow-current.json") or {}
    end_ms = flow.get("end_ms")
    age = now.timestamp() - end_ms / 1000 if type(end_ms) is int else None
    for instrument, key in (("BTC-USDT", "okx_spot"), ("BTC-USDT-SWAP", "okx_swap")):
        windows = flow.get("instruments", {}).get(instrument, {}).get("rolling_windows", {})
        h4 = windows.get("4h", {})
        coverage = h4.get("reconciled_m5")
        status = "missing" if age is None else "stale" if not 0 <= age <= 600 else (
            "volume_reconciled" if coverage == 48 and h4.get("delta_btc_reconciled") is not None else "partial")
        repairs = flow.get("spot_backfill" if key == "okx_spot" else "futures_backfill") or {}
        components[key] = {"status": status, "age_seconds": round(age) if age is not None else None,
                           "h4_buckets": coverage, "h4_required": 48, "backfill_error": repairs.get("error"),
                           "sequence_certified": False}
    delivery = read_json(data_dir / "BTC-report-delivery-audit-v1.json") or {}
    components["iphone_push"] = {"status": "confirmed" if delivery.get("push_notification_confirmed") is True else "unverified"}
    return {
        "schema_version": "1.0",
        "checked_at_utc": now.isoformat().replace("+00:00", "Z"),
        "classification": "operational_diagnostics_only",
        "components": components,
        "fully_operational_confirmed": False,  # continuous uptime and end-to-end delivery not established
        "core_snapshot_ok": (
            all(components[key]["status"] == "ok" for key in core)
            and components["cloudflare_dispatch"]["status"] == "last_dispatch_observed"
            and tv["status"] == "event_history_present"),
        "notes": [
            "GitHub workflow success does not guarantee five-minute scheduling.",
            "Cloudflare 401 and TradingView 502 require Cloudflare/TradingView logs to diagnose.",
            "Do not use this report as a trading signal."
        ],
    }


def main():
    report = evaluate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(OUT)
    print("BTC system health:", report["fully_operational_confirmed"])
    for key, value in report["components"].items():
        print(key, value["status"])


if __name__ == "__main__":
    main()
