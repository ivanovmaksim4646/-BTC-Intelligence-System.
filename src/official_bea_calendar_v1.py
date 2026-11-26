"""Read-only official BEA machine-readable release calendar, public domain.

Government release timestamps are explicit UTC offsets. This parser does not
invent market consensus, actual prints, revisions, or Bitcoin reactions.
"""
from __future__ import annotations
import datetime as dt
import json
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

URL="https://apps.bea.gov/API/signup/release_dates.json"
DATA=Path("data")
OUTPUT=DATA/"BTC-official-bea-calendar-v1.json"
TZ=ZoneInfo("Europe/Warsaw")
SERIES={
    "Gross Domestic Product":"GDP",
    "Personal Income and Outlays":"PERSONAL_INCOME_PCE",
}
def parse_bea(raw,now=None,lookahead_days=90):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone_required")
    now=now.astimezone(dt.timezone.utc)
    if isinstance(raw,(str,bytes)):
        if len(raw)>1000000:raise ValueError("oversized_response")
        raw=json.loads(raw)
    if not isinstance(raw,dict):raise ValueError("invalid_bea_response")
    events=[]
    for series,category in SERIES.items():
        item=raw.get(series)
        if not isinstance(item,dict) or not isinstance(item.get("release_dates"),list):
            raise ValueError("missing_official_series_"+category)
        for iso in item["release_dates"]:
            if not isinstance(iso,str):raise ValueError("invalid_release_date")
            try:date=dt.datetime.fromisoformat(iso.replace("Z","+00:00"))
            except ValueError as exc:raise ValueError("invalid_release_date") from exc
            if date.tzinfo is None:raise ValueError("unverified_release_timezone")
            when=date.astimezone(dt.timezone.utc)
            if now-dt.timedelta(hours=24)<=when<=now+dt.timedelta(days=lookahead_days):
                events.append({
                    "agency":"BEA","category":category,"title":series,
                    "release_at_utc":when.isoformat(),
                    "release_at_poland":when.astimezone(TZ).isoformat(),
                    "source_url":URL,
                    "previous":None,"consensus":None,"actual":None,
                    "surprise":None,"btc_reaction":None,
                    "classification":"official_published_schedule_only"
                })
    by_key={(e["category"],e["release_at_utc"]):e for e in events}
    return {
        "schema_version":"1.0","status":"official_schedule_only" if by_key else "no_releases_in_horizon",
        "generated_at_utc":now.isoformat(),"source":URL,
        "events":sorted(by_key.values(),key=lambda e:(e["release_at_utc"],e["category"])),
        "forecast_provenance":"unavailable","decision":"NO_TRADE","trade_signal":None,
        "note":"Official future schedule; no consensus, actual, or BTC reaction inferred."
    }
def collect(now=None):
    req=urllib.request.Request(URL,headers={"User-Agent":"BTC-Intelligence-public-calendar/1.0"})
    with urllib.request.urlopen(req,timeout=15) as r:
        if r.geturl()!=URL:raise ValueError("unexpected_redirect")
        raw=r.read(1000001)
    if len(raw)>1000000:raise ValueError("oversized_response")
    return parse_bea(raw,now)
def main():
    DATA.mkdir(exist_ok=True)
    out=collect()
    temp=OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(OUTPUT)
    print("BEA calendar:",out["status"],"events:",len(out["events"]))
if __name__=="__main__":main()
