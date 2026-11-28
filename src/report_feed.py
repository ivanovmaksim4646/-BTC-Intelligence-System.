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


def early_spot_watch(current, now):
    """Independent spot-only observation; not a trade or calibrated forecast."""
    import math
    stamp = timestamp(current.get("collected_at_utc"))
    result = {"status": "unavailable", "direction": None, "source": "Kraken Spot",
              "trade_signal": None, "windows": {}, "experimental": True}
    if not stamp or not 0 <= (now-stamp).total_seconds() <= MAX_AGE_SECONDS:
        return result
    for tf, secs in (("M5",300),("M15",900),("H1",3600),("H4",14400)):
        row = ((current.get("order_flow") or {}).get("spot") or {}).get(tf) or {}
        end, start = timestamp(row.get("window_end_utc")), timestamp(row.get("window_start_utc"))
        if (row.get("coverage") != "complete" or not end or not start
                or end.timestamp() != int(now.timestamp())//secs*secs
                or (end-start).total_seconds() != secs):
            continue
        b,s = row.get("buy_volume"),row.get("sell_volume")
        if any(type(x) not in (int,float) or not math.isfinite(x) or x<0 for x in (b,s)) or b+s<=0:
            continue
        result["windows"][tf] = {"end_utc": row["window_end_utc"], "delta_btc": b-s,
                                 "volume_btc": b+s, "pressure": (b-s)/(b+s)}
    w = result["windows"]
    result["status"] = "observed" if w else "unavailable"
    if "M15" in w and "H1" in w:
        a,b = w["M15"]["pressure"],w["H1"]["pressure"]
        if a>0.1 and b>0.1:
            result["direction"] = "WATCH LONG"
        elif a< -0.1 and b< -0.1:
            result["direction"] = "WATCH SHORT"
    result["limitation"] = "Experimental aligned spot aggression; nested windows are not independent; price response and persistence not established."
    return result


def spot_persistence(history, now):
    """Use disjoint reconciled OKX spot M5 buckets and same-instrument prices."""
    import math
    out = {"source":"OKX BTC-USDT", "status":"unavailable", "trade_signal":None,
           "experimental":True}
    if not isinstance(history,list):
        return out
    end = int(now.timestamp())//300*300000
    index = {}
    conflicts = set()
    for row in history:
        if not isinstance(row,dict) or row.get("instrument")!="BTC-USDT" or row.get("volume_reconciled") is not True:
            continue
        t = row.get("end_ms")
        if type(t) is not int or row.get("start_ms")!=t-300000 or t%300000:
            continue
        if t in index and index[t]!=row:
            conflicts.add(t)
        index[t]=row
    needed = list(range(end-3300000,end+1,300000))
    if any(t not in index or t in conflicts for t in needed):
        return out
    try:
        rows = [tuple(float(index[t][k]) for k in ("delta_btc_reconciled","volume_btc_reconciled","open_usdt","close_usdt")) for t in needed]
    except (KeyError,ValueError,TypeError,OverflowError):
        return out
    if any(not all(math.isfinite(x) for x in row) or row[1]<=0 or abs(row[0])>row[1] or min(row[2:])<=0 for row in rows):
        return out
    blocks = []
    for i in range(0,12,3):
        part = rows[i:i+3]
        delta = sum(x[0] for x in part)
        volume = sum(x[1] for x in part)
        blocks.append({"end_ms":needed[i+2],"delta_btc":delta,"pressure":delta/volume,
                       "price_return":part[-1][3]/part[0][2]-1})
    out.update(status="observed",end_ms=end,blocks=blocks,
               coverage="volume_reconciled_not_sequence_certified",direction=None)
    for sign,label in ((1,"LONG"),(-1,"SHORT")):
        if all(sign*b["pressure"]>0.1 for b in blocks[-2:]):
            out["direction"]="WATCH "+label
            out["price_response"]="aligned" if all(sign*b["price_return"]>0 for b in blocks[-2:]) else "mixed_or_divergent"
    return out


def okx_visible_liquidity(doc, wall, now):
    """Expose already collected levels, never infer liquidations or executions."""
    import math
    out = {"source":"OKX BTC-USDT-SWAP","status":"unavailable","liquidation_heatmap":None}
    def fresh(d, classification):
        if not isinstance(d,dict) or d.get("source")!=out["source"] or d.get("classification")!=classification:
            return False
        t=timestamp(d.get("generated_at_utc"))
        return t is not None and 0 <= (now-t).total_seconds() <= MAX_AGE_SECONDS
    if not fresh(doc,"public_rest_snapshot_research_only"):
        return out
    book=doc.get("book") or {}
    t=book.get("timestamp_ms")
    if book.get("status")!="snapshot_only" or type(t) is not int or not 0<=now.timestamp()*1000-t<=MAX_AGE_SECONDS*1000:
        return out
    def positive(v):
        return type(v) in (int,float) and math.isfinite(v) and v>0
    bid,ask=book.get("best_bid"),book.get("best_ask")
    if not positive(bid) or not positive(ask) or bid>=ask:
        return out
    for side in ("bid","ask"):
        rows=book.get(side+"_walls")
        if not isinstance(rows,list) or not rows or len(rows)>3:
            return out
        if any(not isinstance(x,dict) or not positive(x.get("price")) or not positive(x.get("btc")) or
               (x["price"]>bid if side=="bid" else x["price"]<ask) for x in rows):
            return out
        out[side+"_levels"]=[{"price_usdt":x["price"],"size_btc":x["btc"]} for x in rows]
    out.update(status="snapshot_only",timestamp_ms=t,best_bid=bid,best_ask=ask,
               depth_levels=book.get("depth_levels"),persistence=None,
               limitation="Sampled top-three levels within fetched depth; not full market or liquidation map.")
    if fresh(wall,"sampled_top3_resting_price_zone_persistence_only") and wall.get("sample_last_ms")==t and wall.get("status")=="sampled_comparison_available":
        out["persistence"]={k:wall.get(k) for k in ("samples_considered","sample_first_ms","sample_last_ms","persistent_bid_zones","persistent_ask_zones","gaps_verified_continuous")}
    return out


def compact_book(current, now):
    book = current.get("order_book") or {}
    stamp = timestamp(book.get("snapshot_time_utc"))
    if not stamp or not 0 <= (now-stamp).total_seconds() <= MAX_AGE_SECONDS:
        return {"status": "unavailable"}
    return {"status": "snapshot_only", "snapshot_time_utc": book["snapshot_time_utc"],
            "spot": book.get("spot"), "futures": book.get("futures"),
            "limitation": "Resting orders, not executed volume or liquidation heatmap."}


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
        "early_spot_watch": early_spot_watch(current, now),
        "resting_order_book": compact_book(current, now),
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


def compact_chart(doc, context, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(doc, dict):
        return {"status": "missing", "timeframes": {}}
    stamp = timestamp(doc.get("collected_at_utc"))
    if (doc.get("source") != "OKX BTC-USDT-SWAP" or doc.get("status") != "verified"
            or not stamp or not 0 <= (now-stamp).total_seconds() <= MAX_AGE_SECONDS):
        return {"status": "unverified_or_stale", "timeframes": {}}
    import math
    out = {}
    for tf, seconds in (("5m",300),("15m",900),("1h",3600),("4h",14400),("1d",86400)):
        item = (doc.get("timeframes") or {}).get(tf) or {}
        bars = item.get("bars")
        if item.get("status") != "ok" or not isinstance(bars,list) or len(bars)<3:
            continue
        selected = bars[-40:]
        prev = 0
        valid = True
        for b in selected:
            if not isinstance(b,dict) or any(type(b.get(k)) not in (int,float) or not math.isfinite(b[k]) for k in ("t","o","h","l","c")):
                valid=False
                break
            if (type(b["t"]) is not int or b["t"]<=prev or b["t"]+seconds>stamp.timestamp()+5
                    or b["l"]<=0 or b["l"]>min(b["o"],b["c"]) or b["h"]<max(b["o"],b["c"])):
                valid=False
                break
            prev=b["t"]
        if not valid:
            continue
        c = ((context or {}).get("timeframes") or {}).get(tf) or {}
        cs = timestamp((context or {}).get("generated_at_utc"))
        aligned = ((context or {}).get("source")==doc["source"] and cs is not None
                   and 0 <= (now-cs).total_seconds() <= MAX_AGE_SECONDS
                   and c.get("last_closed_candle_open_s")==selected[-1]["t"]
                   and c.get("last_close")==selected[-1]["c"])
        out[tf] = {"bars":selected,"structure":c if aligned else None}
    return {"status":"verified_subset" if out else "unavailable","source":doc["source"],
            "collected_at_utc":doc["collected_at_utc"],"timeframes":out}

def backup_market_context(now, fetch=None):
    """Independent free public feeds; never substitute for same-venue paper evidence."""
    import math
    from concurrent.futures import ThreadPoolExecutor
    from urllib.request import Request, urlopen
    def get(url):
        with urlopen(Request(url,headers={"User-Agent":"BTC-Intelligence/1.0","Accept":"application/json"}),timeout=8) as response:
            return json.load(response)
    fetch = fetch or get
    end = int(now.timestamp())//300*300000
    def number(x):
        if isinstance(x,bool):
            raise ValueError("invalid number")
        n=float(x)
        if not math.isfinite(n):
            raise ValueError("nonfinite")
        return n
    def binance(url):
        raw=fetch(url)
        if not isinstance(raw,list):
            raise ValueError("unexpected kline response")
        index={}
        for row in raw:
            if not isinstance(row,list) or len(row)<11 or type(row[0]) is not int or type(row[6]) is not int:
                raise ValueError("invalid kline")
            t=row[0]
            if t%300000 or row[6]!=t+299999:
                raise ValueError("invalid window")
            if t>=end:
                continue
            volume,buy=number(row[5]),number(row[9])
            if not 0<=buy<=volume or t in index:
                raise ValueError("invalid volume or duplicate")
            index[t]=(volume,2*buy-volume)
        windows={}
        for label,n in (("M5",1),("M15",3),("H1",12),("H4",48)):
            keys=list(range(end-n*300000,end,300000))
            if all(t in index for t in keys):
                v=sum(index[t][0] for t in keys)
                d=sum(index[t][1] for t in keys)
                windows[label]={"end_ms":end,"start_ms":keys[0],"volume_btc":v,
                                "delta_btc":d,"coverage":"exchange_closed_kline_taker_volume",
                                "pressure":d/v if v>0 else None}
        return {"status":"observed" if windows else "unavailable","windows":windows,
                "classification":"exchange_kline_taker_buy_base_volume_not_trade_sequence"}
    def bybit(url):
        raw=fetch(url)
        if not isinstance(raw,dict) or raw.get("retCode")!=0:
            raise ValueError("exchange error")
        b=raw["result"]
        t=b.get("ts")
        if b.get("s")!="BTCUSDT" or type(t) is not int or not 0<=dt.datetime.now(dt.timezone.utc).timestamp()*1000-t<=180000:
            raise ValueError("stale or wrong instrument")
        sides={}
        for key in ("b","a"):
            rows=b[key]
            if not isinstance(rows,list) or not 0<len(rows)<=50:
                raise ValueError("invalid depth")
            levels=[(number(x[0]),number(x[1])) for x in rows]
            prices=[x[0] for x in levels]
            if any(min(x)<=0 for x in levels) or len(set(prices))!=len(prices) or prices!=sorted(prices,reverse=key=="b"):
                raise ValueError("invalid levels")
            sides[key]=levels
        if sides["b"][0][0]>=sides["a"][0][0]:
            raise ValueError("crossed book")
        return {"status":"snapshot_only","timestamp_ms":t,"best_bid":sides["b"][0][0],
                "best_ask":sides["a"][0][0],
                "bid_levels":[{"price_usdt":p,"size_btc":v} for p,v in sorted(sides["b"],key=lambda x:x[1],reverse=True)[:3]],
                "ask_levels":[{"price_usdt":p,"size_btc":v} for p,v in sorted(sides["a"],key=lambda x:x[1],reverse=True)[:3]],
                "depth_levels":{"bid":len(sides["b"]),"ask":len(sides["a"])},
                "classification":"resting_orders_not_liquidations"}
    specs={
        "Binance Spot BTCUSDT":(binance,"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=50"),
        "Binance USD-M BTCUSDT":(binance,"https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=50"),
        "Bybit Spot BTCUSDT":(bybit,"https://api.bybit.com/v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=50"),
        "Bybit Linear BTCUSDT":(bybit,"https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=50")
    }
    def safe(spec):
        fn,url=spec
        try:
            return fn(url)
        except Exception as exc:
            from urllib.error import HTTPError
            result = {"status":"unavailable","error_type":type(exc).__name__}
            if isinstance(exc, HTTPError):
                result["http_status"] = exc.code
                result["endpoint"] = url.split("?")[0]
                result["failure_category"] = ("restricted_or_forbidden" if exc.code in (403,451) else
                    "rate_limit" if exc.code in (418,429) else "server_error" if exc.code >= 500 else "http_error")
            return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=dict(zip(specs,pool.map(safe,specs.values())))
    return {"generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "sources":result,"trade_signal":None,"liquidation_heatmap":None,
            "policy":"Independent market context only; no cross-venue substitution or aggregation."}


def main():
    report = build(
        read("BTC-intelligence-current.json"), read("BTC-analysis-current.json"),
        read("BTC-structure-current.json"), read("BTC-setup-candidates.json"),
        read("BTC-scheduler-health.json"), okx=read("BTC-okx-confluence-v2.json"),
        bea=read("BTC-official-bea-calendar-v1.json"),
        bls_fed=read("BTC-official-bls-fed-calendar-v1.json")
    )
    # Compact, independently timestamped report-reader payload. No signal changes.
    report["chart_snapshot"] = compact_chart(read("BTC-okx-futures-candles.json"),
                                             read("BTC-okx-market-context-v1.json"))
    report["okx_reconciled_flow"] = read("BTC-okx-reconciled-flow-current.json")
    report["okx_spot_persistence"] = spot_persistence(read("BTC-okx-reconciled-m5-history.json"), dt.datetime.now(dt.timezone.utc))
    report["okx_visible_liquidity"] = okx_visible_liquidity(read("BTC-okx-liquidity-derivatives-v1.json"), read("BTC-okx-wall-persistence-v1.json"), dt.datetime.now(dt.timezone.utc))
    report["backup_market_context"] = backup_market_context(dt.datetime.now(dt.timezone.utc))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    temp.replace(OUTPUT)
    print("BTC report data status:", report["report_data_status"],
          ", ".join(report["reasons"]) if report["reasons"] else "all checks passed")


if __name__ == "__main__":
    main()
