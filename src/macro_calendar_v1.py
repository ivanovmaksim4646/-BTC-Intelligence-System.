"""Macro Calendar v1: strictly validated official release-event ingestion.

This module accepts dated events transcribed from official agency schedules.
It deliberately does not scrape websites or infer forecasts, actual values, or
Bitcoin price reactions. Keep it outside the production workflow until vetted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ALLOWED = {"BLS", "BEA", "Federal Reserve"}
WARSAW = ZoneInfo("Europe/Warsaw")
NEW_YORK = ZoneInfo("America/New_York")
CATEGORIES = {"CPI", "PPI", "NFP", "UNEMPLOYMENT", "GDP", "PCE", "FOMC"}
SOURCE_DOMAINS = {
    "BLS": "https://www.bls.gov/",
    "BEA": "https://www.bea.gov/",
    "Federal Reserve": "https://www.federalreserve.gov/",
}


def normalize_event(event: dict, now: dt.datetime | None = None) -> dict:
    """Convert an official US release timestamp to Poland time without DST guessing."""
    if not isinstance(event, dict):
        raise ValueError("event_not_object")
    agency = event.get("agency")
    category = event.get("category")
    if agency not in ALLOWED or category not in CATEGORIES:
        raise ValueError("unknown_agency_or_category")
    if agency == "BLS" and category not in {"CPI", "PPI", "NFP", "UNEMPLOYMENT"}:
        raise ValueError("invalid_agency_category")
    if agency == "BEA" and category not in {"GDP", "PCE"}:
        raise ValueError("invalid_agency_category")
    if agency == "Federal Reserve" and category != "FOMC":
        raise ValueError("invalid_agency_category")
    title, url, local_iso = (event.get(k) for k in ("title", "source_url", "release_et"))
    if not isinstance(title, str) or not title.strip() or len(title) > 180:
        raise ValueError("invalid_title")
    if not isinstance(url, str) or not url.startswith(SOURCE_DOMAINS[agency]):
        raise ValueError("unverified_source_domain")
    if not isinstance(local_iso, str):
        raise ValueError("missing_release_timestamp")
    try:
        value = dt.datetime.fromisoformat(local_iso)
    except ValueError as exc:
        raise ValueError("invalid_release_timestamp") from exc
    if value.tzinfo is not None:
        raise ValueError("expected_naive_new_york_wall_time")
    # Reject DST nonexistent and ambiguous local timestamps unless independently resolved.
    variants = [value.replace(tzinfo=NEW_YORK, fold=fold) for fold in (0, 1)]
    valid = [v for v in variants if v.astimezone(dt.timezone.utc).astimezone(NEW_YORK).replace(tzinfo=None) == value]
    if len(valid) != 2 or valid[0].utcoffset() != valid[1].utcoffset():
        raise ValueError("ambiguous_or_nonexistent_us_time")
    ny = valid[0]
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now_must_be_aware")
    if not -366 <= (ny - now).total_seconds() / 86400 <= 366:
        raise ValueError("timestamp_outside_one_year_window")
    return {
        "agency": agency,
        "category": category,
        "title": title.strip(),
        "source_url": url,
        "release_at_utc": ny.astimezone(dt.timezone.utc).isoformat(),
        "release_at_poland": ny.astimezone(WARSAW).isoformat(),
        "previous": None,
        "consensus": None,
        "actual": None,
        "surprise": None,
        "btc_reaction": None,
        "classification": "official_schedule_only_not_actual_or_signal",
    }


def build(events: list[dict], now: dt.datetime | None = None) -> dict:
    if not isinstance(events, list):
        raise ValueError("events_must_be_array")
    normalized = [normalize_event(e, now) for e in events]
    unique = {}
    for item in normalized:
        key = (item["agency"], item["category"], item["release_at_utc"])
        if key in unique and item != unique[key]:
            raise ValueError("conflicting_duplicate_release")
        unique[key] = item
    return {
        "schema_version": "1.0",
        "status": "schedule_only" if unique else "no_verified_events",
        "timezone": "Europe/Warsaw",
        "events": sorted(unique.values(), key=lambda x: (x["release_at_utc"], x["agency"], x["category"])),
        "decision": "NO_TRADE",
        "trade_signal": None,
        "note": "An empty calendar is NOT evidence that there are no forthcoming releases.",
    }


def main() -> None:
    base = Path(__file__).resolve().parents[1] / "data"
    # A manually verified schedule can be supplied later by a separate source adapter.
    source = base / "BTC-official-release-schedule-input.json"
    if not source.exists():
        events = []
    else:
        events = json.loads(source.read_text(encoding="utf-8"))
    result = build(events)
    out = base / "BTC-macro-calendar-v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out)
    print("Macro calendar:", result["status"], "verified events", len(result["events"]))


if __name__ == "__main__":
    main()
