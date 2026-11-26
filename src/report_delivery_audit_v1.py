"""Read-only audit of BTC report readiness; never claims push delivery."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

DATA=Path(__file__).resolve().parents[1]/"data"
OUTPUT=DATA/"BTC-report-delivery-audit-v1.json"
WARSAW=ZoneInfo("Europe/Warsaw")
SLOTS={"morning":"08:15","pre_new_york":"13:45"}
MAX_AGE_SECONDS=900

def parse_utc(value):
    if not isinstance(value,str):return None
    try:
        instant=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        if instant.tzinfo is None:return None
        return instant.astimezone(dt.timezone.utc)
    except ValueError:return None

def evaluate(feed, scheduler, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("now_requires_timezone")
    now=now.astimezone(dt.timezone.utc)
    feed=feed if isinstance(feed,dict) else {}
    scheduler=scheduler if isinstance(scheduler,dict) else {}
    collected=parse_utc(feed.get("collected_at_utc"))
    generated=parse_utc(feed.get("generated_at_utc"))
    trigger=parse_utc(scheduler.get("recorded_at_utc"))
    issues=[]
    def valid(ts):
        return ts is not None and 0<=(now-ts).total_seconds()<=MAX_AGE_SECONDS
    freshness=valid(collected) and valid(generated)
    if not freshness:issues.append("feed_missing_stale_or_future")
    if collected and generated and generated<collected:
        freshness=False;issues.append("feed_generated_before_collection")
    if not valid(trigger):issues.append("trigger_missing_stale_or_future")
    if feed.get("report_data_status") not in ("verified","ok"):
        issues.append("report_data_not_unqualified")
    confluence=feed.get("okx_confluence")
    if not isinstance(confluence,dict) or confluence.get("status")!="verified":
        issues.append("confluence_unverified_or_partial")
    if feed.get("trade_signal") is not None:
        issues.append("unexpected_signal_payload")
    local=now.astimezone(WARSAW)
    due={}
    for key,hhmm in SLOTS.items():
        h,m=(int(part) for part in hhmm.split(":"))
        planned=local.replace(hour=h,minute=m,second=0,microsecond=0)
        due[key]={"local_time":hhmm,
                  "time_zone":"Europe/Warsaw",
                  "today_slot_reached":local>=planned}
    return {
        "schema_version":"1.0","checked_at_utc":now.isoformat().replace("+00:00","Z"),
        "classification":"report_readiness_audit_not_delivery_receipt",
        "feed_fresh":freshness,"trigger_fresh":valid(trigger),
        "slots":due,
        "can_claim_unqualified_report":len(issues)==0,
        "delivery_confirmed":False,
        "push_notification_confirmed":False,
        "delivery_attempt_id":None,
        "delivery_provider_receipt":None,
        "issues":issues,
        "decision":"NO_TRADE","trade_signal":None,
        "note":"File generation, scheduler invocation and mobile push delivery are different evidence layers."
    }

def main():
    def load(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,UnicodeError,ValueError):return None
    out=evaluate(load("BTC-report-feed.json"),load("BTC-scheduler-health.json"))
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUTPUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUTPUT)
    print("REPORT DELIVERY AUDIT:",out["issues"],"push confirmed:",out["push_notification_confirmed"])
if __name__=="__main__":main()
