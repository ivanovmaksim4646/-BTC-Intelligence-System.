#!/usr/bin/env python3
"""BTC setup confluence v1: transparent evidence ladder; never an entry signal.

Links existing IFVG(H1-W1), HTF FVG-POI, QM(M5/M15), Kraken Spot/Futures
Delta and Kraken OI. Does not confuse chronological or directional proximity
with a proven POI touch, futures execution, or a tested trade.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HTF_SECONDS = {"H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}
LTF_SECONDS = {"M5": 300, "M15": 900}
MAX_AGE = dt.timedelta(minutes=15)

def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        x = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return x.astimezone(dt.timezone.utc) if x.utcoffset() is not None else None
    except ValueError:
        return None

def valid_number(v):
    return type(v) in (int, float) and math.isfinite(v)

def epoch_age(now, value, duration, limit):
    if not valid_number(value):
        return False
    try:
        close = dt.datetime.fromtimestamp(value + duration, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return False
    return dt.timedelta(0) <= now - close <= limit

def read_json(name):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}

def evaluate(models, report, structure, tv_events=None, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:
        raise ValueError("now must be timezone aware")
    result = {
        "schema_version": "1.0",
        "classification": "research_confluence_only",
        "evaluated_at_utc": now.astimezone(dt.timezone.utc).isoformat(),
        "decision": "NO_TRADE",
        "trade_signal": None,
        "entry": None, "stop_loss": None, "take_profit": None, "rr": None,
        "probability": None,
        "futures_price_levels_verified": False,
        "htf_poi_touch_verified": False,
        "qm_retest_verified": False,
        "models": {
            "IFVG_H1_W1": {"status": "unavailable", "observations": []},
            "HTF_POI_QM_LTF": {"status": "unavailable", "observations": []}
        },
        "reasons": [],
    }
    reasons = result["reasons"]
    collected = timestamp(report.get("collected_at_utc"))
    structured = timestamp(structure.get("collected_at_utc"))
    if (models.get("source") != "Kraken Spot XBTUSD" or
        structure.get("source") != "Kraken Spot XBTUSD" or
        models.get("futures_verified") is not False):
        reasons.append("source_or_provenance_unverified")
        return result
    if (report.get("report_data_status") != "ready" or not collected or
        not dt.timedelta(0) <= now - collected <= MAX_AGE or not structured or
        abs((structured-collected).total_seconds()) > 120):
        reasons.append("missing_stale_or_unsynchronized_inputs")
        return result

    # M5 flow must be complete and directional; Delta and window CVD
    # are the same measurement, not independent votes.
    flow = (report.get("order_flow") or {}).get("M5") or {}
    coverage = flow.get("coverage") or {}
    if coverage.get("spot") != "complete" or coverage.get("futures") != "complete":
        reasons.append("incomplete_m5_spot_or_futures_flow")
        return result
    spot, futures = flow.get("spot_delta"), flow.get("futures_delta")
    if not valid_number(spot) or not valid_number(futures):
        reasons.append("missing_m5_delta")
        return result
    flow_direction = "long" if spot > 0 and futures > 0 else (
        "short" if spot < 0 and futures < 0 else None)
    if not flow_direction:
        reasons.append("spot_futures_delta_disagree_or_neutral")

    # OI is contextual only; no claim that a change proves direction.
    oi = report.get("open_interest") or {}
    oi_source_time = timestamp(oi.get("source_time_utc"))
    oi_change = (oi.get("change") or {}).get("H1")
    oi_fresh = (oi_source_time and
                dt.timedelta(0) <= now - oi_source_time <= MAX_AGE and
                valid_number(oi.get("value")) and valid_number(oi_change))
    oi_context = {
        "venue": oi.get("venue", "Kraken Futures"),
        "h1_change": oi_change if oi_fresh else None,
        "direction": ("increasing" if oi_change > 0 else "decreasing" if oi_change < 0 else "flat")
                     if oi_fresh else "unavailable",
        "interpretation": "non_directional_context_only",
    }
    if not oi_fresh:
        reasons.append("oi_missing_or_stale")

    # Only events recent enough to make a live observation; historical
    # archive records cannot be promoted into new setups.
    ifvgs = []
    for tf, items in (models.get("ifvg_htf") or {}).items():
        if tf not in HTF_SECONDS or not isinstance(items, list):
            continue
        for x in items:
            if (isinstance(x, dict) and x.get("direction") in ("long", "short") and
                valid_number(x.get("low")) and valid_number(x.get("high")) and
                x["low"] < x["high"] and epoch_age(
                    now, x.get("inverted_at"), HTF_SECONDS[tf],
                    dt.timedelta(seconds=HTF_SECONDS[tf] * 2))):
                ifvgs.append({"timeframe": tf, "direction": x["direction"],
                              "low": x["low"], "high": x["high"],
                              "inverted_at": x["inverted_at"], "flow_aligned":
                              x["direction"] == flow_direction if flow_direction else False,
                              "oi": oi_context,
                              "retest_observed": x.get("retest_observed") is True,
                              "futures_validated": False})
    ifvgs.sort(key=lambda x: x["inverted_at"], reverse=True)
    result["models"]["IFVG_H1_W1"] = {
        "status": "context_observed_not_trade" if ifvgs else "no_recent_inversion",
        "observations": ifvgs[:10], "entry_signal": False,
    }

    # A valid POI+QM needs independent proof that SAME-venue LTF candles
    # entered HTF POI before QM formation. Current model has no touch times,
    # no confirmed QM retest and no validated futures POI. We may display
    # direction-compatible research pairs but must NOT mark them confirmed.
    pairs = []
    for tf, points in (models.get("htf_poi_fvg_candidates") or {}).items():
        if tf not in HTF_SECONDS or not isinstance(points, list):
            continue
        for p in points:
            if not isinstance(p, dict) or not valid_number(p.get("low")) or not valid_number(p.get("high")) or p["low"] >= p["high"]:
                continue
            direction = "long" if p.get("kind") == "bullish_fvg" else (
                "short" if p.get("kind") == "bearish_fvg" else None)
            if not direction:
                continue
            for ltf, patterns in (models.get("qm_ltf") or {}).items():
                if ltf not in LTF_SECONDS or not isinstance(patterns, list):
                    continue
                for q in patterns:
                    if (not isinstance(q, dict) or q.get("direction") != direction or
                        not epoch_age(now, q.get("structural_extreme_time"),
                                      LTF_SECONDS[ltf], dt.timedelta(minutes=45))):
                        continue
                    if not valid_number(q.get("left_shoulder")) or not valid_number(q.get("head_extreme")):
                        continue
                    # This is deliberately not a touch confirmation.
                    pairs.append({"htf": tf, "ltf": ltf, "direction": direction,
                                  "poi": {"low": p["low"], "high": p["high"],
                                          "kind": p["kind"]},
                                  "qm_shoulder": q["left_shoulder"],
                                  "qm_head": q["head_extreme"],
                                  "qm_extreme_time": q["structural_extreme_time"],
                                  "flow_aligned": direction == flow_direction if flow_direction else False,
                                  "oi": oi_context,
                                  "poi_touch_verified": False,
                                  "qm_retest_verified": False,
                                  "futures_validated": False})
    pairs.sort(key=lambda p: p["qm_extreme_time"], reverse=True)
    result["models"]["HTF_POI_QM_LTF"] = {
        "status": "unverified_context_pairs" if pairs else "no_recent_directional_pair",
        "observations": pairs[:10], "entry_signal": False,
    }
    reasons.extend(["poi_touch_sequence_not_proven", "qm_retest_not_proven",
                    "futures_chart_not_verified", "entry_sl_tp_rr_not_validated"])
    return result

def main():
    result = evaluate(read_json("BTC-strategy-models-v1.json"),
                      read_json("BTC-report-feed.json"),
                      read_json("BTC-structure-current.json"))
    target = DATA / "BTC-setup-confluence-v1.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    temp.replace(target)
    print("Setup confluence v1:", result["decision"], "(research only)")

if __name__ == "__main__":
    main()
