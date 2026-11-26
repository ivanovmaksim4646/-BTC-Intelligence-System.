"""Independent official BLS/Fed calendar sources; fail closed on missing data."""
import datetime as dt
import json
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
from src.economic_calendar_v1 import parse as parse_ics
NY=ZoneInfo("America/New_York")
PL=ZoneInfo("Europe/Warsaw")
ICS="https://www.bls.gov/schedule/news_release/bls.ics"
FED="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FED_TIME="https://www.federalreserve.gov/newsevents/pressreleases/monetary20240809a.htm"
CATEGORIES={"Consumer Price Index":"CPI","Producer Price Index":"PPI","Employment Situation":"NFP_UNEMPLOYMENT","Job Openings and Labor Turnover Survey":"JOLTS","Job Openings and Labor Turnover":"JOLTS"}
OUTPUT=Path("data/BTC-official-bls-fed-calendar-v1.json")
class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self,d): self.parts.append(d)
def plain(raw):
    p=Text();p.feed(raw);return " ".join(" ".join(p.parts).split())
def download(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"BTC-Intelligence-public-calendar/1.0"}),timeout=12) as r:
        raw=r.read(3000001)
    if len(raw)>3000000:raise ValueError("oversized")
    return raw.decode("utf-8-sig")
def event(agency,kind,title,when,url):
    return {"agency":agency,"category":kind,"title":title,"release_at_utc":when.astimezone(dt.timezone.utc).isoformat(),"release_at_poland":when.astimezone(PL).isoformat(),"source_url":url,"previous":None,"consensus":None,"actual":None,"surprise":None,"btc_reaction":None,"classification":"official_published_schedule_only"}
def parse_bls_html(raw,now,url):
    t=plain(raw)
    if "All times on calendar are Eastern Time" not in t:raise ValueError("timezone_unverified")
    pat=r"([A-Z][a-z]+, [A-Z][a-z]+ \d{1,2}, \d{4})\s+(\d{1,2}:\d{2}\s+[AP]M)\s+("+"|".join(CATEGORIES)+r")\s+for\b"
    rows=[]
    for date,clock,title in re.findall(pat,t):
        when=dt.datetime.strptime(date+" "+clock,"%A, %B %d, %Y %I:%M %p").replace(tzinfo=NY)
        if now<=when<=now+dt.timedelta(days=45):rows.append(event("BLS",CATEGORIES[title],title,when,url))
    return rows
def parse_fed(raw,now):
    t=plain(raw)
    rows=[]
    # Only ordinary two-day meetings; strategy-only October 2027 explicitly excluded.
    for year in sorted({now.year,(now+dt.timedelta(days=90)).year}):
        m=re.search(r"\b"+str(year)+r" FOMC Meetings\b(.*?)(?=\b\d{4} FOMC Meetings\b|$)",t)
        if not m:continue
        for month,first,last in re.findall(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})\b",m.group(1)):
            if year==2027 and month=="October":continue
            if int(last)!=int(first)+1:continue
            when=dt.datetime.strptime(f"{year} {month} {last} 14:00","%Y %B %d %H:%M").replace(tzinfo=NY)
            if now<=when<=now+dt.timedelta(days=90):
                e=event("FED","FOMC","FOMC scheduled policy decision",when,FED);e["time_source_url"]=FED_TIME;rows.append(e)
    # Revised schedules or repeated page sections can show multiple dates for a month.
    # Never choose between conflicting official dates automatically.
    by_month={}
    for e in rows:
        key=e["release_at_poland"][:7]
        by_month.setdefault(key,{})[e["release_at_utc"]]=e
    return [next(iter(v.values())) for v in by_month.values() if len(v)==1]
def bls_collect(now):
    try:
        rows=[event("BLS",e["event"],e["title"],dt.datetime.fromisoformat(e["scheduled_utc"]),ICS) for e in parse_ics(download(ICS),now)]
        if rows:return rows
    except Exception:pass
    rows=[]
    for year in sorted({now.year,(now+dt.timedelta(days=45)).year}):
        for url in (f"https://www.bls.gov/schedule/{year}/",f"https://blsmon1.bls.gov/schedule/{year}/home.htm"):
            try:
                found=parse_bls_html(download(url),now,url)
                if found:rows.extend(found);break
            except Exception:continue
    return rows
def collect(now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    out={"generated_at_utc":now.isoformat(),"sources":{},"events":[],"trade_signal":None}
    for agency,fn in (("BLS",lambda:bls_collect(now)),("FED",lambda:parse_fed(download(FED),now))):
        try:
            rows=fn();out["sources"][agency]={"status":"official_schedule_only" if rows else "unavailable_or_empty","count":len(rows)}
            out["events"].extend(rows)
        except Exception as exc:out["sources"][agency]={"status":"unavailable","error":type(exc).__name__,"count":0}
    out["events"]=sorted({(e["category"],e["release_at_utc"]):e for e in out["events"]}.values(),key=lambda e:e["release_at_utc"])
    return out
def main():
    out=collect();OUTPUT.parent.mkdir(exist_ok=True)
    tmp=OUTPUT.with_suffix(".tmp");tmp.write_text(json.dumps(out,indent=2)+"\n");tmp.replace(OUTPUT)
    print(json.dumps(out))
if __name__=="__main__":main()
