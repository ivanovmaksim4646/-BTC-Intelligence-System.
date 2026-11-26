"""Research-only Forex Factory weekly JSON adapter.

Source publishes dates, importance, forecast and previous. It does NOT publish
actual results in this feed. No silent source mixing or forecast fabrication.
Public feed access does not itself establish redistribution permission.
"""
from __future__ import annotations
import datetime as dt
import json
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SOURCE="https://nfs.faireconomy.media/ff_calendar_thisweek.json"
WARSAW=ZoneInfo("Europe/Warsaw")
IMPACTS={"Low","Medium","High","Holiday","Non-Economic"}
def parse_weekly(raw, now=None):
    if isinstance(raw,(bytes,bytearray)):
        if len(raw)>1024*1024:raise ValueError("oversized_feed")
        raw=raw.decode("utf-8")
    if isinstance(raw,str):
        if len(raw)>1024*1024:raise ValueError("oversized_feed")
        raw=json.loads(raw)
    if not isinstance(raw,list) or not raw or len(raw)>1000:
        raise ValueError("missing_or_invalid_weekly_feed")
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone_required")
    result=[]
    for item in raw:
        if not isinstance(item,dict):raise ValueError("invalid_item")
        title=item.get("title")
        country=item.get("country")
        impact=item.get("impact")
        if not isinstance(title,str) or not title.strip() or len(title)>180:
            raise ValueError("invalid_title")
        if not isinstance(country,str) or len(country)!=3 or not country.isalpha():
            raise ValueError("invalid_currency")
        if impact not in IMPACTS:raise ValueError("unknown_impact")
        try:
            t=dt.datetime.fromisoformat(item["date"])
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError("invalid_timestamp") from exc
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("timestamp_without_timezone")
        utc=t.astimezone(dt.timezone.utc)
        # Limited to the current weekly schedule; stale archives fail closed.
        if abs((utc-now).total_seconds())>8*86400:
            raise ValueError("event_outside_weekly_horizon")
        forecast=item.get("forecast")
        previous=item.get("previous")
        if not isinstance(forecast,str) or not isinstance(previous,str):
            raise ValueError("invalid_values")
        result.append({"title":title.strip(),"currency":country.upper(),"impact":impact,
                       "release_at_utc":utc.isoformat(),
                       "release_at_poland":t.astimezone(WARSAW).isoformat(),
                       "forecast":forecast.strip() or None,
                       "previous":previous.strip() or None,
                       "actual":None,"btc_reaction":None,
                       "source":SOURCE,
                       "classification":"weekly_indicative_schedule_no_actuals"})
    result.sort(key=lambda x:(x["release_at_utc"],x["currency"],x["title"]))
    return {"status":"weekly_schedule_only","source":SOURCE,"events":result,
            "actuals_available":False,"decision":"NO_TRADE","trade_signal":None,
            "caveat":"External feed access and downstream usage terms require separate verification."}

def fetch_weekly(now=None):
    req=Request(SOURCE,headers={"User-Agent":"BTC-Intelligence-research/1.0"})
    with urlopen(req,timeout=12) as response:
        if response.geturl()!=SOURCE:raise ValueError("unexpected_redirect")
        raw=response.read(1024*1024+1)
    return parse_weekly(raw,now)
