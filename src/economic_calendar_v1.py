"""Official BLS calendar pilot. No inferred forecasts or release times."""
import datetime as dt
import json,re
from zoneinfo import ZoneInfo
from pathlib import Path
from src.market_breadth_macro_v1 import fetch
URL="https://www.bls.gov/schedule/news_release/bls.ics"
NY=ZoneInfo("America/New_York")
PL=ZoneInfo("Europe/Warsaw")
def parse(raw,now):
    if "BEGIN:VCALENDAR" not in raw:raise ValueError("not a calendar")
    raw=re.sub(r"\r?\n[ \t]","",raw)
    events={}
    for block in re.findall(r"BEGIN:VEVENT\s*(.*?)END:VEVENT",raw,re.S):
        fields={}
        for line in block.splitlines():
            if ":" in line:
                key,value=line.split(":",1);fields[key]=value
        title=fields.get("SUMMARY","")
        kind=next((k for phrase,k in (("consumer price index","CPI"),("producer price index","PPI"),("employment situation","NFP_UNEMPLOYMENT"),("job openings and labor turnover","JOLTS")) if phrase in title.lower()),None)
        if not kind or fields.get("STATUS")=="CANCELLED":continue
        key=next((k for k in fields if k=="DTSTART" or k.startswith("DTSTART;")),None)
        if not key:continue
        value=fields[key]
        try:
            if value.endswith("Z"):t=dt.datetime.strptime(value,"%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
            elif "TZID=America/New_York" in key or "TZID=US/Eastern" in key:t=dt.datetime.strptime(value,"%Y%m%dT%H%M%S").replace(tzinfo=NY)
            else:continue
        except ValueError:continue
        if not now<=t<=now+dt.timedelta(days=45):continue
        ident=kind+":"+t.isoformat()
        events[ident]={"event":kind,"title":title,"scheduled_utc":t.astimezone(dt.timezone.utc).isoformat(),"scheduled_warsaw":t.astimezone(PL).isoformat(),"source":URL,"forecast":None,"actual":None}
    return sorted(events.values(),key=lambda x:x["scheduled_utc"])
def main():
    now=dt.datetime.now(dt.timezone.utc)
    out={"generated_at_utc":now.isoformat(),"source":URL,"status":"unavailable","events":[],"coverage":"BLS only; FOMC and consensus not integrated"}
    try:
        out["events"]=parse(fetch(URL),now)
        out["status"]="observed" if out["events"] else "empty_unverified"
    except Exception as exc:out["error"]=type(exc).__name__
    p=Path("data/BTC-economic-calendar-v1.json");p.parent.mkdir(exist_ok=True)
    t=p.with_suffix(".tmp");t.write_text(json.dumps(out,indent=2)+"\n");t.replace(p)
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
