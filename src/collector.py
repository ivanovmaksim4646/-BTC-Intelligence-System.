#!/usr/bin/env python3
"""Incremental, public-API-only BTC order-flow collector for GitHub Actions."""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATE_DIR = ROOT / "state"
STATE_FILE = STATE_DIR / "collector-state.json"
CURRENT_FILE = DATA / "BTC-intelligence-current.json"
HISTORY_FILE = DATA / "BTC-intelligence-history.csv"
BOOK_FILE = DATA / "BTC-orderbook-history.jsonl"
ERROR_FILE = DATA / "BTC-intelligence-errors.csv"

SPOT_PAIR = "XBTUSD"
PERP_SYMBOL = "PF_XBTUSD"
WINDOWS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
RETAIN_SECONDS = 6 * 3600
# Bootstrap only enough data for M5/M15/H1. H4 becomes complete after the
# collector has accumulated four hours. This keeps the first Actions run short.
BOOTSTRAP_SECONDS = 90 * 60
HTTP_TIMEOUT = 25
MAX_ATTEMPTS = 3
UA = "btc-intelligence-github/1.0"

HISTORY_FIELDS = [
    "record_key", "collected_at_utc", "record_type", "venue", "symbol",
    "timeframe", "window_start_utc", "window_end_utc", "price_usd",
    "buy_volume", "sell_volume", "total_volume", "delta", "cvd_change",
    "volume_unit", "trade_count", "coverage", "coverage_detail",
    "open_interest", "oi_unit", "oi_change", "funding_relative_hourly",
    "basis_usd", "basis_percent", "bid_depth_top20", "ask_depth_top20",
    "book_unit", "source_time_utc", "source",
]


def iso(epoch: float | int) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    temp.replace(path)


def classify_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if isinstance(exc, socket.gaierror) or "name resolution" in text or "resolve" in text:
        return "DNS"
    if "proxy" in text or "tunnel" in text:
        return "proxy"
    if isinstance(exc, urllib.error.HTTPError):
        return "HTTP"
    if isinstance(exc, (OSError, urllib.error.URLError)):
        return "network"
    return "application"


def request_json(url: str) -> dict[str, Any]:
    last: BaseException | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.load(response)
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(f"Kraken business error: {payload['error']}")
            return payload
        except BaseException as exc:  # retry all transport and Kraken business failures
            last = exc
            if attempt < MAX_ATTEMPTS:
                time.sleep(attempt)
    assert last is not None
    raise RuntimeError(f"{classify_error(last)} after {MAX_ATTEMPTS} attempts: {last}") from last


def public(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = "https://api.kraken.com/0/public/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return request_json(url)


def futures(path: str) -> dict[str, Any]:
    return request_json("https://futures.kraken.com" + path)


def append_error(kind: str, message: str, collected_at: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    new = not ERROR_FILE.exists()
    with ERROR_FILE.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["time_utc", "class", "message"])
        if new:
            writer.writeheader()
        writer.writerow({"time_utc": collected_at, "class": kind, "message": message[:1000]})


def fetch_spot_incremental(state: dict[str, Any], now_ns: int) -> tuple[dict[int, dict[str, float | int]], dict[str, Any]]:
    spot = state.setdefault("spot", {})
    cursor = int(spot.get("last_cursor_ns") or (now_ns - BOOTSTRAP_SECONDS * 1_000_000_000))
    coverage_start = int(spot.get("coverage_start_ns") or cursor)
    buckets: dict[int, dict[str, float | int]] = {
        int(key): value for key, value in spot.get("minute_buckets", {}).items()
    }
    recent_ids = list(spot.get("recent_trade_ids", []))
    seen = set(recent_ids)
    pages = 0

    while True:
        payload = public("Trades", {"pair": SPOT_PAIR, "since": cursor})["result"]
        pair_key = next(key for key in payload if key != "last")
        rows = payload[pair_key]
        next_cursor = int(payload["last"])
        for row in rows:
            price, volume, stamp, side = float(row[0]), float(row[1]), float(row[2]), row[3]
            trade_id = f"{stamp:.9f}|{price:.8f}|{volume:.8f}|{side}"
            if trade_id in seen:
                continue
            seen.add(trade_id)
            recent_ids.append(trade_id)
            minute = int(stamp) // 60 * 60
            bucket = buckets.setdefault(minute, {"buy": 0.0, "sell": 0.0, "count": 0})
            bucket["buy" if side == "b" else "sell"] = float(bucket["buy" if side == "b" else "sell"]) + volume
            bucket["count"] = int(bucket["count"]) + 1
        pages += 1
        if next_cursor <= cursor or not rows or next_cursor >= now_ns:
            cursor = max(cursor, next_cursor)
            break
        cursor = next_cursor
        if pages > 250:
            raise RuntimeError("coverage: Spot pagination exceeded 250 pages")

    cutoff = now_ns // 1_000_000_000 - RETAIN_SECONDS
    buckets = {minute: row for minute, row in buckets.items() if minute >= cutoff}
    recent_ids = recent_ids[-5000:]
    spot.update({
        "last_cursor_ns": cursor,
        "coverage_start_ns": coverage_start,
        "minute_buckets": {str(key): value for key, value in sorted(buckets.items())},
        "recent_trade_ids": recent_ids,
        "last_pages": pages,
    })
    return buckets, spot


def fetch_spot_ohlc() -> list[list[Any]]:
    payload = public("OHLC", {"pair": SPOT_PAIR, "interval": 5})["result"]
    key = next(key for key in payload if key != "last")
    return payload[key]


def aggregate_spot(
    buckets: dict[int, dict[str, float | int]], ohlc: list[list[Any]], coverage_start_ns: int, now: int
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for label, seconds in WINDOWS.items():
        end = now // seconds * seconds
        start = end - seconds
        selected = [row for minute, row in buckets.items() if start <= minute < end]
        buy = sum(float(row["buy"]) for row in selected)
        sell = sum(float(row["sell"]) for row in selected)
        trade_total = buy + sell
        ohlc_total = sum(float(row[6]) for row in ohlc if start <= int(row[0]) < end)
        expected_bars = seconds // 300
        ohlc_bars = sum(1 for row in ohlc if start <= int(row[0]) < end)
        relative_error = abs(trade_total - ohlc_total) / max(ohlc_total, 1e-12)
        cursor_covers = coverage_start_ns <= start * 1_000_000_000
        complete = cursor_covers and ohlc_bars == expected_bars and relative_error <= 0.005
        output[label] = {
            "window_start_utc": iso(start), "window_end_utc": iso(end),
            "buy_volume": round(buy, 8), "sell_volume": round(sell, 8),
            "total_volume": round(trade_total, 8), "delta": round(buy - sell, 8),
            "cvd_change": round(buy - sell, 8), "unit": "BTC",
            "trade_count": sum(int(row["count"]) for row in selected), "coverage": "complete" if complete else "partial",
            "coverage_detail": {
                "cursor_covers_window": cursor_covers, "ohlc_bars": ohlc_bars,
                "expected_ohlc_bars": expected_bars, "trade_vs_ohlc_relative_error": round(relative_error, 8),
            },
        }
    return output


def analytics(metric: str, since: int, to: int) -> dict[str, Any]:
    return futures(f"/api/charts/v1/analytics/{PERP_SYMBOL}/{metric}?interval=300&since={since}&to={to}")["result"]


def aggregate_futures(result: dict[str, Any], now: int) -> dict[str, dict[str, Any]]:
    timestamps = list(map(int, result["timestamp"]))
    raw = result["data"]
    if isinstance(raw, dict):
        rows = [
            [float(buy), float(sell)]
            for buy, sell in zip(raw["buy_volume"], raw["sell_volume"])
        ]
    else:
        rows = [list(map(float, row)) for row in raw]
    bars = dict(zip(timestamps, rows))
    output: dict[str, dict[str, Any]] = {}
    for label, seconds in WINDOWS.items():
        end = now // seconds * seconds
        start = end - seconds
        selected = [bars[stamp] for stamp in range(start, end, 300) if stamp in bars]
        expected = seconds // 300
        buy = sum(row[0] for row in selected)
        sell = sum(row[1] for row in selected)
        output[label] = {
            "window_start_utc": iso(start), "window_end_utc": iso(end),
            "buy_volume": round(buy, 8), "sell_volume": round(sell, 8),
            "total_volume": round(buy + sell, 8), "delta": round(buy - sell, 8),
            "cvd_change": round(buy - sell, 8), "unit": "BTC-equivalent contracts",
            "base_bars": len(selected), "coverage": "complete" if len(selected) == expected else "partial",
            "coverage_detail": {"base_bars": len(selected), "expected_base_bars": expected},
        }
    return output


def oi_changes(result: dict[str, Any], now: int) -> dict[str, float | None]:
    bars = {int(ts): list(map(float, row)) for ts, row in zip(result["timestamp"], result["data"])}
    changes: dict[str, float | None] = {}
    for label, seconds in WINDOWS.items():
        end = now // seconds * seconds
        first = bars.get(end - seconds)
        last = bars.get(end - 300)
        changes[label] = round(last[3] - first[3], 8) if first and last else None
    return changes


def top_levels(levels: list[list[Any]], mid: float, limit: int = 10) -> list[dict[str, float]]:
    rows = [
        {"price_usd": float(row[0]), "size": float(row[1])}
        for row in levels if abs(float(row[0]) / mid - 1) <= 0.02
    ]
    return sorted(rows, key=lambda row: row["size"], reverse=True)[:limit]


def append_history(rows: list[dict[str, Any]]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    existing_keys: set[str] = set()
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open(newline="", encoding="utf-8") as handle:
            existing_keys = {row["record_key"] for row in csv.DictReader(handle)}
    new_file = not HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS, extrasaction="ignore")
        if new_file:
            writer.writeheader()
        for row in rows:
            if row["record_key"] not in existing_keys:
                writer.writerow(row)
                existing_keys.add(row["record_key"])


def write_book_snapshot(snapshot: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with BOOK_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) + "\n")


def collect() -> None:
    started = time.time()
    now = int(started)
    now_ns = now * 1_000_000_000
    collected_at = iso(started)
    DATA.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_json(STATE_FILE, {"schema_version": "1.0"})
    previous_success = state.get("last_success_utc")

    spot_buckets, spot_state = fetch_spot_incremental(state, now_ns)
    # Persist the raw cursor/buffer checkpoint before processing other endpoints.
    # A later Futures or formatting failure must not force another full Spot bootstrap.
    state.update({"last_attempt_utc": collected_at, "last_status": "collecting"})
    atomic_json(STATE_FILE, state)
    spot_ohlc = fetch_spot_ohlc()
    spot_flow = aggregate_spot(spot_buckets, spot_ohlc, int(spot_state["coverage_start_ns"]), now)

    # Align lookback to the start of the last closed H4 window. A simple
    # now-minus-N-hours request can cut off its first few 5-minute bars.
    lookback = min(now // seconds * seconds - seconds for seconds in WINDOWS.values()) - 600
    futures_flow_raw = analytics("cvd", lookback, now)
    oi_raw = analytics("open-interest", lookback, now)
    futures_flow = aggregate_futures(futures_flow_raw, now)
    oi_delta = oi_changes(oi_raw, now)

    ticker_payload = futures("/derivatives/api/v3/tickers")
    perp = next(row for row in ticker_payload["tickers"] if row["symbol"] == PERP_SYMBOL)
    spot_ticker_payload = public("Ticker", {"pair": SPOT_PAIR})["result"]
    spot_ticker = next(iter(spot_ticker_payload.values()))
    spot_depth_payload = public("Depth", {"pair": SPOT_PAIR, "count": 100})["result"]
    spot_depth = next(iter(spot_depth_payload.values()))
    futures_depth = futures(f"/derivatives/api/v3/orderbook?symbol={PERP_SYMBOL}&depth=100")["orderBook"]

    spot_mid = (float(spot_depth["bids"][0][0]) + float(spot_depth["asks"][0][0])) / 2
    perp_mid = (float(perp["bid"]) + float(perp["ask"])) / 2
    book = {
        "snapshot_time_utc": collected_at,
        "spot": {"venue": "Kraken Spot", "unit": "BTC", "bids": top_levels(spot_depth["bids"], spot_mid), "asks": top_levels(spot_depth["asks"], spot_mid)},
        "futures": {"venue": "Kraken Futures", "unit": "BTC-equivalent contracts", "bids": top_levels(futures_depth["bids"], perp_mid), "asks": top_levels(futures_depth["asks"], perp_mid)},
        "limitation": "Snapshots show resting liquidity only; movement/cancellation requires comparing stored snapshots.",
    }

    mark = float(perp["markPrice"])
    index = float(perp["indexPrice"])
    missed = 0
    if previous_success:
        prev = dt.datetime.fromisoformat(previous_success.replace("Z", "+00:00")).timestamp()
        missed = max(0, math.floor((started - prev) / 3600) - 1)

    current = {
        "schema_version": "2.0",
        "status": "verified" if all(v["coverage"] == "complete" for v in [*spot_flow.values(), *futures_flow.values()]) else "partial",
        "collected_at_utc": collected_at,
        "health": {
            "previous_success_utc": previous_success, "missed_hourly_runs_estimate": missed,
            "duration_seconds": round(time.time() - started, 3), "spot_pages_this_run": spot_state["last_pages"],
            "freshness_limit_seconds": 5400,
        },
        "market": {"asset": "BTC", "spot_symbol": SPOT_PAIR, "perpetual_symbol": PERP_SYMBOL},
        "price": {
            "spot": {"value": float(spot_ticker["c"][0]), "unit": "USD/BTC", "venue": "Kraken Spot", "source_time_utc": collected_at},
            "futures": {"value": float(perp["last"]), "mark": mark, "index": index, "unit": "USD/BTC", "venue": "Kraken Futures", "source_time_utc": ticker_payload["serverTime"]},
        },
        "order_flow": {"spot": spot_flow, "futures": futures_flow},
        "derivatives": {
            "open_interest": {"value": float(perp["openInterest"]), "unit": "BTC-equivalent contracts", "change": oi_delta, "source_time_utc": ticker_payload["serverTime"]},
            "funding": {"absolute": perp.get("fundingRate"), "relative_hourly": perp.get("relativeFundingRate"), "relative_percent_hourly": (perp.get("relativeFundingRate") or 0) * 100, "source_time_utc": ticker_payload["serverTime"]},
            "basis": {"mark_minus_index_usd": round(mark - index, 8), "percent": round((mark / index - 1) * 100, 10), "source_time_utc": ticker_payload["serverTime"]},
        },
        "order_book": book,
        "definitions": {
            "delta": "taker_buy_volume minus taker_sell_volume",
            "cvd_change": "sum of Delta inside the exact closed window; not absolute CVD",
            "absolute_cvd": None,
        },
    }

    history_rows: list[dict[str, Any]] = []
    for venue, symbol, unit, flows in [
        ("Kraken Spot", SPOT_PAIR, "BTC", spot_flow),
        ("Kraken Futures", PERP_SYMBOL, "BTC-equivalent contracts", futures_flow),
    ]:
        for timeframe, flow in flows.items():
            row = {
                "record_key": f"{venue}|{symbol}|{timeframe}|{flow['window_end_utc']}",
                "collected_at_utc": collected_at, "record_type": "order_flow", "venue": venue,
                "symbol": symbol, "timeframe": timeframe, **flow,
                "price_usd": float(spot_ticker["c"][0]) if venue == "Kraken Spot" else float(perp["last"]),
                "volume_unit": unit,
                "coverage_detail": json.dumps(flow["coverage_detail"], separators=(",", ":")),
                "source_time_utc": ticker_payload["serverTime"] if venue == "Kraken Futures" else collected_at,
                "source": "Kraken public REST",
            }
            if venue == "Kraken Futures":
                row.update({
                    "open_interest": float(perp["openInterest"]), "oi_unit": unit,
                    "oi_change": oi_delta[timeframe], "funding_relative_hourly": perp.get("relativeFundingRate"),
                    "basis_usd": round(mark - index, 8), "basis_percent": round((mark / index - 1) * 100, 10),
                })
            history_rows.append(row)

    append_history(history_rows)
    write_book_snapshot(book)
    state.update({"last_success_utc": collected_at, "last_status": current["status"]})
    for key in ("last_error", "last_error_class"):
        state.pop(key, None)
    atomic_json(CURRENT_FILE, current)
    atomic_json(STATE_FILE, state)


def main() -> int:
    collected_at = iso(time.time())
    try:
        collect()
        print(f"BTC Intelligence updated at {collected_at}")
        return 0
    except BaseException as exc:
        kind = classify_error(exc)
        append_error(kind, repr(exc), collected_at)
        state = load_json(STATE_FILE, {"schema_version": "1.0"})
        state.update({"last_attempt_utc": collected_at, "last_status": "error", "last_error_class": kind, "last_error": str(exc)[:1000]})
        atomic_json(STATE_FILE, state)
        print(f"Collection failed: {kind}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
