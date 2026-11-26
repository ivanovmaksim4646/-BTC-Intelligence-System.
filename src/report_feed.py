#!/usr/bin/env python3
"""Conservative report feed for automated BTC briefs.

All timestamps are UTC. Report readers must RECHECK collected_at_utc vs
their own wall clock; 'ready' was evaluated only when the file was written.
No probability, entry, target or standalone trade advice is generated here.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "BTC-report-feed.json"
MAX_AGE_SECONDS = 900
TIMEFRAMES = ("M5", "M15", "H1", "H4")


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        instant = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.astimezone(dt.timezone.utc) if instant.tzinfo else None
    except ValueError:
        return None


def read(name):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def build(current, analysis, structure, watchlist, scheduler, now=None, okx=None, bea=None, bls_fed=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    now = now.astimezone(dt.timezone.utc)
    current = current if isinstance(current, dict) else {}
    analysis = analysis if isinstance(analysis, dict) else {}
    structure = structure if isinstance(structure, dict) else {}
    watchlist = watchlist if isinstance(watchlist, dict) else {}
    scheduler = scheduler if isinstance(scheduler, dict) else {}
    instant = timestamp(current.get("collected_at_utc"))
    age = (now - instant).total_seconds() if instant else None
    fresh = age is not None and -90 <= age <= MAX_AGE_SECONDS
    spot = (current.get("order_flow") or {}).get("spot") or {}
    futures = (current.get("order_flow") or {}).get("futures") or {}
    coverage = {
        tf: {
            "spot": (spot.get(tf) or {}).get("coverage", "missing"),
            "futures": (futures.get(tf) or {}).get("coverage", "missing")
        }
        for tf in TIMEFRAMES
    }
    complete = (current.get("status") == "verified"
                and all(all(state == "complete" for state in sides.values())
                        for sides in coverage.values()))
    analysis_sync = (analysis.get("data_collected_at_utc")
                     == current.get("collected_at_utc") and analysis.get("fresh") is True)
    structure_sync = (structure.get("collected_at_utc") is not None
                      and abs((timestamp(structure.get("collected_at_utc")) - instant).total_seconds()) <= 120
                      if instant and timestamp(structure.get("collected_at_utc")) else False)
    watchlist_sync = (watchlist.get("evaluated_at_utc") is not None
                      and abs((timestamp(watchlist.get("evaluated_at_utc")) - instant).total_seconds()) <= 120
                      if instant and timestamp(watchlist.get("evaluated_at_utc")) else False)
    reasons = []
    if not fresh:
        reasons.append("stale_or_missing_collection")
    if not complete:
        reasons.append("incomplete_spot_or_futures_coverage")
    if not analysis_sync:
        reasons.append("order_flow_not_synchronized")
    if not structure_sync:
        reasons.append("structure_not_synchronized")
    if not watchlist_sync:
        reasons.append("watchlist_not_synchronized")
    ready = not reasons
    observations = {}
    for tf in TIMEFRAMES:
        item = (analysis.get("timeframes") or {}).get(tf) or {}
        s = spot.get(tf) or {}
        f = futures.get(tf) or {}
        observations[tf] = {
            "window_end_utc": item.get("window_end_utc"),
            "spot_delta": s.get("delta") if coverage[tf]["spot"] == "complete" else None,
            "futures_delta": f.get("delta") if coverage[tf]["futures"] == "complete" else None,
            "spot_volume": s.get("total_volume") if coverage[tf]["spot"] == "complete" else None,
            "futures_volume": f.get("total_volume") if coverage[tf]["futures"] == "complete" else None,
            "observation": item.get("observation", "unavailable"),
            "coverage": coverage[tf],
        }
    okx = okx if isinstance(okx, dict) else {}
    okx_stamp = timestamp(okx.get("generated_at_utc"))
    okx_valid = (okx.get("source") == "OKX BTC-USDT-SWAP"
                 and okx.get("classification") == "okx_confluence_research_only"
                 and okx_stamp is not None
                 and 0 <= (now - okx_stamp).total_seconds() <= MAX_AGE_SECONDS)
    okx_section = {"status": "missing_or_stale", "data": None}
    if okx_valid:
        close = okx.get("m5_close_s")
        if type(close) is int and close % 300 == 0 and 0 <= now.timestamp() - close <= 420:
            okx_section = {"status": "research_partial" if okx.get("missing") else "research_only",
                           "data": {k: okx.get(k) for k in (
                               "source", "generated_at_utc", "m5_close_s", "structure",
                               "flow", "derivatives", "liquidity", "support", "conflicts",
                               "missing", "watch_direction", "paper_candidates_count")},
                           "trade_signal": None}
    calendar = {"status": "missing_or_stale", "events": []}
    if isinstance(bea, dict):
        stamp = timestamp(bea.get("generated_at_utc"))
        if (stamp and 0 <= (now - stamp).total_seconds() <= 129600
                and bea.get("source") == "https://apps.bea.gov/API/signup/release_dates.json"
                and bea.get("status") in ("official_schedule_only", "no_releases_in_horizon")
                and isinstance(bea.get("events"), list)):
            calendar = {"status": bea["status"], "source": bea["source"],
                        "generated_at_utc": bea["generated_at_utc"],
                        "max_age_seconds": 129600,
                        "events": [e for e in bea["events"] if isinstance(e, dict)
                                   and timestamp(e.get("release_at_utc"))
                                   and now <= timestamp(e["release_at_utc"])],
                        "coverage": "BEA GDP/PCE only; BLS/FOMC unavailable"}
    # Keep independently verified BEA data if another source is unavailable.
    sources = {"BEA": {"status": calendar["status"]}}
    for agency in ("BLS", "FED"):
        sources[agency] = {"status": "missing_or_stale"}
    if isinstance(bls_fed, dict):
        stamp = timestamp(bls_fed.get("generated_at_utc"))
        if stamp and 0 <= (now-stamp).total_seconds() <= 129600:
            for agency in ("BLS", "FED"):
                info = (bls_fed.get("sources") or {}).get(agency) or {}
                sources[agency] = {"status": info.get("status", "unavailable"),
                                   "generated_at_utc": bls_fed["generated_at_utc"]}
                if info.get("status") != "official_schedule_only":
                    continue
                for e in bls_fed.get("events") or []:
                    if (isinstance(e, dict) and e.get("agency")==agency
                            and e.get("classification")=="official_published_schedule_only"
                            and timestamp(e.get("release_at_utc"))
                            and now <= timestamp(e["release_at_utc"])):
                        calendar["events"].append(e)
    calendar["events"] = sorted({(e.get("agency"),e.get("category"),e["release_at_utc"]):e
                                  for e in calendar["events"]}.values(),
                                 key=lambda e:(e["release_at_utc"],e.get("category","")))
    calendar["sources"] = sources
    calendar["coverage"] = "Official schedule only; source-specific gaps possible; JOLTS and conflicting FOMC dates not guaranteed; consensus/actual/reaction unavailable"
    if calendar["events"]:
        calendar["status"] = "official_schedule_only"
    return {
        "economic_calendar": calendar,
        "okx_confluence": okx_section,
        "schema_version": "1.1",
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "collected_at_utc": current.get("collected_at_utc"),
        "collection_age_seconds_at_generation": round(age) if age is not None else None,
        "max_allowed_age_seconds": MAX_AGE_SECONDS,
        "report_data_status": "ready" if ready else "withhold_or_qualify",
        "reasons": reasons,
        "source": "Kraken Spot/Futures via BTC Intelligence GitHub Actions",
        "scheduler": {"event": scheduler.get("event"), "source": scheduler.get("source"),
                      "slot": scheduler.get("slot")},
        "order_flow": observations,
        "open_interest": (current.get("derivatives") or {}).get("open_interest"),
        "funding": (current.get("derivatives") or {}).get("funding"),
        "basis": (current.get("derivatives") or {}).get("basis"),
        "structure": (structure.get("timeframes") or {}),
        "watchlist": (watchlist.get("timeframes") or {}),
        "trade_signal": None,
        "signal_policy": "No confirmed trade entry. Do not synthesize directional probabilities, targets, SL or RR.",
        "notes": [
            "Age must be recomputed at report-reading time using collected_at_utc.",
            "Window Delta is exactly the same measurement as window CVD change, not an independent confirmation.",
            "Legacy fields are Kraken-only; OKX confluence is separately labeled. No cross-venue combination or unverified macro, ETF or liquidation heatmap values.",
            "Structure is based on Kraken Spot closed candles; TradingView events are recorded separately."
        ]
    }


def main():
    report = build(
        read("BTC-intelligence-current.json"), read("BTC-analysis-current.json"),
        read("BTC-structure-current.json"), read("BTC-setup-candidates.json"),
        read("BTC-scheduler-health.json"), okx=read("BTC-okx-confluence-v2.json"),
        bea=read("BTC-official-bea-calendar-v1.json"),
        bls_fed=read("BTC-official-bls-fed-calendar-v1.json")
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    temp.replace(OUTPUT)
    print("BTC report data status:", report["report_data_status"],
          ", ".join(report["reasons"]) if report["reasons"] else "all checks passed")


if __name__ == "__main__":
    main()
