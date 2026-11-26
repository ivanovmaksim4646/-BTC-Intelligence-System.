"""Strict, backwards-compatible validation of TradingView observational alerts.

v1 Inside Bar/Sweep payload remains unchanged. v2 structure events are
algorithmic observations, never authenticated trade instructions.
"""
from __future__ import annotations
import datetime as dt
import math
import re

LEGACY = {"h1_inside_bar", "h1_sweep_high_reject", "h1_sweep_low_reclaim"}
STRUCTURE = {
    "m5_bullish_break", "m5_bearish_break",
    "m5_bullish_fvg", "m5_bearish_fvg",
    "m5_sweep_pdh", "m5_sweep_pdl",
}
BASE = {"source", "event", "symbol", "timeframe", "time_ms", "price"}
IB_FIELDS = {"mother_high", "mother_low", "inside_high", "inside_low"}
V2_FIELDS = {"level", "level_kind", "volume"}
VALID_LEVEL_KINDS = {"pivot_high", "pivot_low", "fvg_upper", "fvg_lower", "pdh", "pdl"}


def valid_price(x):
    return type(x) in (int, float) and math.isfinite(x) and 0 < x < 1e8


def validate(event, now_ms=None):
    if not isinstance(event, dict):
        raise ValueError("payload must be an object")
    if not BASE <= event.keys():
        raise ValueError("missing base fields")
    source = event["source"]
    name = event["event"]
    if source == "btc-intelligence-tv-v1" and name in LEGACY:
        if set(event) != BASE | IB_FIELDS:
            raise ValueError("unexpected v1 fields")
        bounds = [event[k] for k in ("mother_low", "inside_low", "inside_high", "mother_high")]
        if not all(map(valid_price, bounds)) or bounds != sorted(bounds) or len(set(bounds)) != 4:
            raise ValueError("invalid Inside Bar range")
    elif source == "btc-intelligence-tv-v2" and name in STRUCTURE:
        if set(event) != BASE | V2_FIELDS:
            raise ValueError("unexpected v2 fields")
        if event["level_kind"] not in VALID_LEVEL_KINDS or not valid_price(event["level"]):
            raise ValueError("invalid structure level")
        if type(event["volume"]) not in (float, int) or not math.isfinite(event["volume"]) or event["volume"] < 0:
            raise ValueError("invalid volume")
        required_kind = {
            "m5_bullish_break": "pivot_high", "m5_bearish_break": "pivot_low",
            "m5_bullish_fvg": "fvg_upper", "m5_bearish_fvg": "fvg_lower",
            "m5_sweep_pdh": "pdh", "m5_sweep_pdl": "pdl",
        }[name]
        if event["level_kind"] != required_kind:
            raise ValueError("event-level mismatch")
    else:
        raise ValueError("unknown alert type")
    if not isinstance(event["symbol"], str) or not re.fullmatch(
        r"(?:[A-Z0-9_]+:)?(?:BTC|XBT)[A-Z0-9_.]*", event["symbol"].upper()
    ):
        raise ValueError("not a BTC symbol")
    if event["timeframe"] != "5":
        raise ValueError("not M5")
    if type(event["time_ms"]) is not int:
        raise ValueError("invalid close timestamp")
    if now_ms is None:
        now_ms = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    if abs(now_ms - event["time_ms"]) > 15 * 60 * 1000:
        raise ValueError("stale or future alert")
    if not valid_price(event["price"]):
        raise ValueError("invalid price")
    return event
