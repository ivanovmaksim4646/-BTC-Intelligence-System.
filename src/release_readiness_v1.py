"""Independent, fail-closed read-only BTC release readiness audit."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-release-readiness-v1.json"
INSTRUMENTS=("BTC-USDT","BTC-USDT-SWAP")
WINDOWS=("5m","15m","1h","4h")
def parse_time(value):
    if not isinstance(value,str):return None
    try:
        t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
        return t.astimezone(dt.timezone.utc) if t.tzinfo else None
    except ValueError:return None
def evaluate(scheduler,flow,context,paper,health,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone_required")
    now=now.astimezone(dt.timezone.utc)
    scheduler=scheduler if isinstance(scheduler,dict) else {}
    flow=flow if isinstance(flow,dict) else {}
    context=context if isinstance(context,dict) else {}
    paper=paper if isinstance(paper,dict) else {}
    health=health if isinstance(health,dict) else {}
    stamp=parse_time(scheduler.get("recorded_at_utc"))
    age=(now-stamp).total_seconds() if stamp else None
    dispatch=(age is not None and 0<=age<=900
              and scheduler.get("event") in ("workflow_dispatch","schedule"))
    records=flow.get("results") if isinstance(flow.get("results"),list) else []
    instruments=flow.get("instruments") if isinstance(flow.get("instruments"),dict) else {}
    coverage={}
    all_reconciled=True
    for inst in INSTRUMENTS:
        r=instruments.get(inst) if isinstance(instruments.get(inst),dict) else {}
        windows=r.get("rolling_windows") if isinstance(r.get("rolling_windows"),dict) else {}
        coverage[inst]={}
        for window in WINDOWS:
            w=windows.get(window) if isinstance(windows.get(window),dict) else {}
            need=w.get("required_m5");count=w.get("reconciled_m5")
            verified=(type(need) is int and need>0 and type(count) is int and count>=need
                      and w.get("coverage")=="volume_reconciled_not_sequence_certified")
            coverage[inst][window]={"reconciled_buckets":count if type(count) is int else None,
                                    "required_buckets":need if type(need) is int else None,
                                    "volume_reconciled_window":verified,"sequence_certified":False}
            all_reconciled=all_reconciled and verified
    issues=[]
    for inst in INSTRUMENTS:
        observed=next((r for r in records if isinstance(r,dict) and r.get("instrument")==inst),None)
        if not observed or observed.get("volume_reconciled") is not True:
            issues.append(inst+"_latest_m5_not_volume_reconciled")
    if not dispatch:issues.append("scheduler_dispatch_missing_or_stale")
    if health.get("fully_operational_confirmed") is not True:
        issues.append("full_system_health_not_confirmed")
    if not all_reconciled:issues.append("incomplete_reconciled_rolling_windows")
    if context.get("missing") or context.get("conflicts"):
        issues.append("confluence_missing_or_conflicting_evidence")
    if paper.get("execution_enabled") is not False or paper.get("decision")!="NO_TRADE":
        issues.append("paper_execution_safety_unverified")
    return {"schema_version":"1.0","generated_at_utc":now.isoformat().replace("+00:00","Z"),
            "classification":"read_only_operational_release_audit_not_market_signal",
            "recent_scheduler_dispatch_observed":dispatch,
            "five_minute_dispatch_continuity_certified":False,
            "okx_rolling_volume_reconciliation":coverage,
            "okx_full_trade_sequence_cvd_certified":False,
            "confluence_decision":context.get("decision") if context.get("decision")=="NO_TRADE" else "unverified",
            "paper_execution_disabled_confirmed":paper.get("execution_enabled") is False,
            "issues":issues,"ready_for_unqualified_live_reporting":False,
            "ready_for_autonomous_trading":False,"decision":"NO_TRADE","trade_signal":None,
            "note":"Volume reconciliation is not complete sequence-certified CVD."}
def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (ValueError,OSError,UnicodeError):return None
    report=evaluate(read("BTC-scheduler-health.json"),
        read("BTC-okx-reconciled-flow-current.json"),
        read("BTC-okx-confluence-v2.json"),read("BTC-okx-paper-signal-v1.json"),
        read("BTC-system-health.json"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    temp=OUT.with_suffix(".tmp")
    temp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    temp.replace(OUT)
    print("BTC release audit:",report["issues"])
if __name__=="__main__":main()
