#!/usr/bin/env python3
"""Same-venue OKX TradingView setup observer and append-only research journal.

TradingView observations are NOT authenticated entry instructions. A matching
closed OKX M5 candle establishes timestamp/venue/price consistency only.
Historical BingX alerts cannot become OKX entries. No Entry/SL/TP or claimed
RR is manufactured. The journal tracks independently corroborated *events*,
not executed or hypothetical trades; RR outcome statistics remain separate.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
try:
    from src.tradingview_validation import validate
except ModuleNotFoundError:
    from tradingview_validation import validate

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
VENUE="OKX BTC-USDT-SWAP"
TV_SYMBOL="OKX:BTCUSDT.P"
JOURNAL=DATA/"BTC-okx-setup-observations-v1.jsonl"
REPORT=DATA/"BTC-okx-setup-validator-v1.json"
MAX_NEW_EVENT_AGE_SECONDS=2*60*60
PRICE_DEVIATION_MAX=0.003
M5=300

def event_id(event):
    key=[event.get(k) for k in ("source","symbol","event","time_ms")]
    raw=json.dumps(key,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]

def evaluate_event(event,candles,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone-aware now required")
    base={"schema_version":"1.0","event_id":event_id(event) if isinstance(event,dict) else None,
          "source":VENUE,"classification":"structure_observation_only",
          "status":"withheld","reasons":[],"entry_confirmed":False,
          "entry":None,"stop_loss":None,"take_profit":None,"rr":None,
          "trade_signal":None,"eligible_for_trade_statistics":False}
    if not isinstance(event,dict):
        base["reasons"].append("invalid_alert")
        return base
    try:
        # Validate the strict TV v1/v2 schema at the original alert time;
        # event age gets separately and strictly checked against now below.
        validate(event,now_ms=event.get("time_ms"))
    except (ValueError,TypeError):
        base["reasons"].append("invalid_alert_schema")
        return base
    if event["symbol"]!=TV_SYMBOL:
        base["reasons"].append("venue_mismatch_not_okx")
        return base
    age=now.timestamp()-event["time_ms"]/1000
    if not 0<=age<=MAX_NEW_EVENT_AGE_SECONDS:
        base["reasons"].append("stale_or_future_alert")
        return base
    frames=candles.get("timeframes") if isinstance(candles,dict) else None
    if (not isinstance(candles,dict) or candles.get("source")!=VENUE
        or candles.get("status")!="verified" or not isinstance(frames,dict)):
        base["reasons"].append("unverified_okx_futures_candles")
        return base
    try: collected=dt.datetime.fromisoformat(candles["collected_at_utc"].replace("Z","+00:00"))
    except (KeyError,ValueError,AttributeError,TypeError):collected=None
    if (not collected or collected.tzinfo is None or
        not dt.timedelta(0)<=now-collected<=dt.timedelta(minutes=15)):
        base["reasons"].append("stale_okx_candle_snapshot")
        return base
    frame=frames.get("5m")
    if not isinstance(frame,dict) or frame.get("status")!="ok":
        base["reasons"].append("missing_okx_m5")
        return base
    bars=frame.get("bars")
    if not isinstance(bars,list) or len(bars)<3:
        base["reasons"].append("insufficient_okx_m5_bars")
        return base
    # Published candle schema stores OPEN time in seconds.
    candle_time=event["time_ms"]//1000-M5
    lookup={b.get("t"):i for i,b in enumerate(bars) if isinstance(b,dict)}
    i=lookup.get(candle_time)
    if i is None or i<2 or event["time_ms"]%1000!=0:
        base["reasons"].append("alert_candle_unavailable_or_misaligned")
        return base
    b=bars[i]
    if abs(b["c"]-event["price"])/b["c"]>PRICE_DEVIATION_MAX:
        base["reasons"].append("okx_price_mismatch")
        return base
    name=event["event"]
    # Independent OHLC validation only for plain 3-candle gaps; other
    # events need swing-state/PDH/PDL reconstruction before confirmation.
    if name=="m5_bullish_fvg":
        if not (b["l"]>bars[i-2]["h"] and abs(b["l"]-event["level"])/b["l"]<=PRICE_DEVIATION_MAX):
            base["reasons"].append("unconfirmed_okx_fvg")
            return base
        kind="three_candle_fvg_consistent"
    elif name=="m5_bearish_fvg":
        if not (b["h"]<bars[i-2]["l"] and abs(b["h"]-event["level"])/b["h"]<=PRICE_DEVIATION_MAX):
            base["reasons"].append("unconfirmed_okx_fvg")
            return base
        kind="three_candle_fvg_consistent"
    else:
        kind="closed_candle_price_consistent_only"
    base.update({"status":"observed_not_trade","reasons":["missing_independent_poi_qm_retest_and_liquidity_target"],
                 "event":name,"symbol":TV_SYMBOL,"event_close_ms":event["time_ms"],
                 "matched_okx_candle_open":candle_time,
                 "corroboration":kind,
                 "ohlc_close":b["c"],"tv_close":event["price"],
                 "side":"long" if ("bullish" in name or name=="m5_sweep_pdl") else "short"
                     if ("bearish" in name or name=="m5_sweep_pdh") else None})
    return base

def evaluate(events,candles,existing_ids=None,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    ids=set(existing_ids or ())
    new=[];audits=[];by_reason={}
    for event in events:
        obs=evaluate_event(event,candles,now)
        if obs["status"]=="observed_not_trade":
            if obs["event_id"] not in ids:
                ids.add(obs["event_id"])
                new.append(obs)
        else:
            for reason in obs["reasons"]:
                by_reason[reason]=by_reason.get(reason,0)+1
        audits.append(obs)
    return {"schema_version":"1.0","evaluated_at_utc":now.isoformat(),
        "source":VENUE,"classification":"venue_pure_tv_setup_validation_research",
        "alerts_inspected":len(events),"okx_observations_new":len(new),
        "rejected_or_unverified":len(events)-sum(x["status"]=="observed_not_trade" for x in audits),
        "reason_counts":by_reason,
        "records_to_append":new,
        "decision":"NO_TRADE","trade_signal":None,
        "note":"No observed event becomes a trade entry without independent POI/QM retest and liquidity target."}

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    events=[]
    p=DATA/"BTC-tradingview-events.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines()[-200:]:
            try:events.append(json.loads(line))
            except ValueError:events.append({})
    known=set()
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:known.add(json.loads(line)["event_id"])
            except (ValueError,KeyError,TypeError):pass
    r=evaluate(events,read("BTC-okx-futures-candles.json"),known)
    JOURNAL.parent.mkdir(parents=True,exist_ok=True)
    if r["records_to_append"]:
        with JOURNAL.open("a",encoding="utf-8") as handle:
            for item in r["records_to_append"]:
                handle.write(json.dumps(item,ensure_ascii=False,separators=(",",":"))+"\n")
    del r["records_to_append"]
    t=REPORT.with_suffix(".json.tmp")
    t.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    t.replace(REPORT)
    print("OKX TV setup validator:",r["alerts_inspected"],"alerts",
          r["okx_observations_new"],"new observations, decision NO_TRADE",r["reason_counts"])

if __name__=="__main__":main()
