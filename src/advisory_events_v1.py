"""Advisory event observations: reported liquidations, dated forecasts, BTC reaction."""
import datetime as dt
import json, math, statistics
from pathlib import Path
from src.market_breadth_macro_v1 import fetch
from src.report_feed import timestamp
DATA=Path("data")
FORECAST_URL="https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CATEGORIES={"Non-Farm Employment Change":"NFP_UNEMPLOYMENT","Unemployment Rate":"NFP_UNEMPLOYMENT",
 "CPI m/m":"CPI","CPI y/y":"CPI","Core CPI m/m":"CPI","PPI m/m":"PPI","Core PPI m/m":"PPI",
 "Federal Funds Rate":"FOMC","Advance GDP q/q":"GDP","Prelim GDP q/q":"GDP","Final GDP q/q":"GDP","Core PCE Price Index m/m":"PERSONAL_INCOME_PCE"}
def positive(v):return type(v) in (float,int) and math.isfinite(v) and v>0
def read(name):
    try:return json.loads((DATA/name).read_text())
    except (OSError,ValueError):return {}
def liquidation_map(doc,now,width=100):
    out={"status":"unavailable","classification":"reported_liquidation_order_price_histogram_not_predicted_heatmap",
         "source":"Bitget USDT-FUTURES BTCUSDT","amount_unit":None,"liquidation_heatmap":None,"bins":[]}
    if doc.get("source")!=out["source"] or doc.get("classification")!="exchange_reported_liquidation_orders_not_execution_certified" or doc.get("status")!="observed_page":return out
    end=int(now.timestamp()*1000);rows=[];seen=set()
    for r in doc.get("records",[]):
        try:t=r["timestamp_ms"];p=float(r["price"]);side=r["position_direction"];amt=r["reported_amount"]
        except (KeyError,ValueError,TypeError):continue
        if type(t) is not int or not 0<=end-t<=86400000 or not positive(p) or side not in ("LONG","SHORT"):continue
        key=(t,r["price"],side,amt)
        if key in seen:continue
        seen.add(key);rows.append((t,p,side))
    bins={}
    for t,p,s in rows:
        k=math.floor(p/width)*width
        cell=bins.setdefault(k,{"low_usdt":k,"high_usdt_exclusive":k+width,"LONG":0,"SHORT":0})
        cell[s]+=1
    if rows:out.update(status="observed_page_partial",records=len(rows),first_ms=min(x[0] for x in rows),last_ms=max(x[0] for x in rows),bins=[bins[k] for k in sorted(bins)])
    out["limitations"]="Only distinct reported rows in one page; not complete events, no USD/BTC amounts, no predicted liquidation levels."
    return out
def forecast_matches(raw,events,now):
    if not isinstance(raw,list):return []
    out=[]
    for row in raw:
        title=row.get("title");category=CATEGORIES.get(title)
        release=timestamp(row.get("date"))
        if row.get("country")!="USD" or not category or not release or release<=now:continue
        match=next((e for e in events if e.get("category")==category and timestamp(e.get("release_at_utc"))==release),None)
        if not match:continue
        f=row.get("forecast")
        if not isinstance(f,str) or not f.strip():continue
        out.append({"title":title,"category":category,"release_at_utc":release.isoformat(),
           "forecast":f,"previous_provider":row.get("previous"),"forecast_observed_at_utc":now.isoformat(),
           "forecast_source":FORECAST_URL,"official_schedule_source":match.get("source_url"),
           "actual":None,"surprise":None})
    return out
def surprise(forecast,actual):
    # Caller must supply identical series, period, units, and independently sourced first release.
    keys=("series","period","unit","release_at_utc")
    if any(not forecast.get(k) or forecast.get(k)!=actual.get(k) for k in keys):return None
    t=timestamp(forecast.get("release_at_utc"));f=timestamp(forecast.get("observed_at_utc"));a=timestamp(actual.get("observed_at_utc"))
    if not t or not f or not a or not f<t<=a or actual.get("first_release_verified") is not True:return None
    x,y=forecast.get("value"),actual.get("value")
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y)):return None
    return y-x
def btc_reaction(event,candles,now):
    release=timestamp(event.get("release_at_utc"))
    if not release or release>now or release.timestamp()%300:return {"status":"not_due_or_unaligned"}
    if candles.get("source")!="OKX BTC-USDT-SWAP" or candles.get("status")!="verified":return {"status":"unavailable"}
    doc=(candles.get("timeframes") or {}).get("5m") or {}
    if doc.get("status")!="ok":return {"status":"unavailable"}
    idx={};conflicts=set()
    for b in doc.get("bars",[]):
        t=b.get("t")
        if type(t) is not int or t%300 or t+300>now.timestamp():continue
        if not all(positive(b.get(k)) for k in ("o","h","l","c")) or not b["l"]<=min(b["o"],b["c"])<=max(b["o"],b["c"])<=b["h"]:continue
        if t in idx and idx[t]!=b:conflicts.add(t)
        idx[t]=b
    start=int(release.timestamp());base=idx.get(start-300)
    out={"status":"missing_baseline","source":candles["source"],"windows":{},"causality_certified":False}
    if not base or start-300 in conflicts:return out
    out.update(status="observed_partial",baseline_close=base["c"])
    for n in (1,3,12):
        ts=list(range(start,start+n*300,300))
        if any(t not in idx or t in conflicts for t in ts):continue
        part=[idx[t] for t in ts];p=base["c"]
        out["windows"][str(n*5)+"m"]={"return_pct":100*(part[-1]["c"]/p-1),
          "max_up_pct":100*(max(x["h"] for x in part)/p-1),"max_down_pct":100*(min(x["l"] for x in part)/p-1)}
    return out
def main():
    now=dt.datetime.now(dt.timezone.utc)
    feed=read("BTC-report-feed.json")
    events=(feed.get("economic_calendar") or {}).get("events") or []
    out={"classification":"advisory_only","generated_at_utc":now.isoformat(),"trade_signal":None,
       "liquidation_observations":liquidation_map(feed.get("bitget_liquidations") or {},now),
       "forecast_source":FORECAST_URL,"forecasts":[],"forecast_status":"unavailable","reactions":[]}
    try:
        raw=json.loads(fetch(FORECAST_URL))
        if not isinstance(raw,list):raise ValueError("unexpected weekly feed")
        out["forecasts"]=forecast_matches(raw,events,now)
        stamps=[t for row in raw if (t:=timestamp(row.get("date")))]
        out["forecast_feed_range_utc"]=[min(stamps).isoformat(),max(stamps).isoformat()] if stamps else None
        upcoming=[t for e in events if (t:=timestamp(e.get("release_at_utc"))) and t>now]
        out["forecast_status"]="matched_upcoming_events" if out["forecasts"] else ("official_events_beyond_weekly_feed" if stamps and upcoming and min(upcoming)>max(stamps) else "no_matching_upcoming_events")
    except Exception as e:out["forecast_error"]=type(e).__name__
    candles=read("BTC-okx-futures-candles.json")
    # Use official calendar records, not only the future-filtered report feed.
    for file in ("BTC-official-bls-fed-calendar-v1.json","BTC-official-bea-calendar-v1.json"):
        for event in read(file).get("events",[]):
            t=timestamp(event.get("release_at_utc"))
            if t and 0<=(now-t).total_seconds()<=86400:
                out["reactions"].append({"event":event,"reaction":btc_reaction(event,candles,now)})
    out["limitations"]=["No predicted liquidation heatmap; no unknown amount totals",
      "Forecast matches official event time and name; actual first-release ingestion and durable forecast archive not yet wired",
      "Reaction requires contiguous closed M5 observations; price movement is not proof of causal attribution"]
    (DATA/"BTC-advisory-events-v1.json").write_text(json.dumps(out,indent=2,allow_nan=False))
    print("advisory events",out["liquidation_observations"]["status"],out["liquidation_observations"].get("records",0),
          out["forecast_status"],out.get("forecast_error"),"matched",len(out["forecasts"]),"reactions",len(out["reactions"]))
if __name__=="__main__":main()
