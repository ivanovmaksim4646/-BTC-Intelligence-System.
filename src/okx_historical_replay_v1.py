#!/usr/bin/env python3
"""Offline historical research, isolated from the forward paper journal."""
import datetime as dt
import json
from pathlib import Path
from collections import Counter
try:
    from src.okx_entry_evidence_gate_v1 import evaluate as gate, VENUE
    from src.okx_setup_validator_v1 import evaluate_event
    from src.okx_outcome_tracker_v1 import check_bar
    from src.rr_outcome_research_v1 import compare_rr_paths, aggregate
except ModuleNotFoundError:
    from okx_entry_evidence_gate_v1 import evaluate as gate, VENUE
    from okx_setup_validator_v1 import evaluate_event
    from okx_outcome_tracker_v1 import check_bar
    from rr_outcome_research_v1 import compare_rr_paths, aggregate

DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-historical-replay-v1.json"
STEPS={"5m":300,"1h":3600,"4h":14400}
WARMUP=30
def stamp(t):
    return dt.datetime.fromtimestamp(t,dt.timezone.utc)
def replay(snapshot,alerts):
    report={"schema_version":"1.0","source":VENUE,"classification":"historical_replay_research_only",
            "decision":"NO_TRADE","trade_signal":None,"performance_verified":False,
            "status":"insufficient_data","warnings":[],"bars_evaluated":0,
            "bars_with_matched_alert":0,"matched_alerts":0,"alert_rejections":{},
            "funnel":{},"reasons":{},"historical_hypotheses":[],
            "statistics":aggregate([]),"by_direction":{d:aggregate([]) for d in ("long","short")}}
    if not isinstance(snapshot,dict) or snapshot.get("source")!=VENUE or snapshot.get("status")!="verified" or snapshot.get("classification")!="closed_futures_candles_research_only":
        report["warnings"].append("unverified_snapshot");return report
    try:
        cutoff=dt.datetime.fromisoformat(snapshot["collected_at_utc"].replace("Z","+00:00"))
        if cutoff.utcoffset() is None:raise ValueError()
        frames={}
        for tf,step in STEPS.items():
            f=snapshot["timeframes"][tf];bars=f["bars"]
            if f["status"]!="ok" or len(bars)<WARMUP or not all(check_bar(b) for b in bars):
                raise ValueError()
            if any(b["t"]%step or b["t"]+step>cutoff.timestamp() or (i and b["t"]-bars[i-1]["t"]!=step) for i,b in enumerate(bars)):
                raise ValueError()
            frames[tf]=bars
    except (ValueError,TypeError,KeyError,AttributeError):
        report["warnings"].append("invalid_or_gapped_closed_history");return report
    m5=frames["5m"]
    report["sample"]={"m5_bars":len(m5),"first_open_utc":stamp(m5[0]["t"]).isoformat(),
        "last_close_utc":stamp(m5[-1]["t"]+300).isoformat(),"warmup_bars":WARMUP,
        "snapshot_collected_at_utc":cutoff.isoformat()}
    by_close={}
    rejects=Counter()
    for a in alerts:
        if not isinstance(a,dict) or a.get("symbol")!="OKX:BTCUSDT.P":
            continue
        try:
            t=a["time_ms"]
            if type(t) is not int or t%300000:raise ValueError()
            close=t//1000
            received=dt.datetime.fromisoformat(a["received_at_utc"].replace("Z","+00:00"))
            # Match only alerts received by the original gate's freshness horizon.
            if not close<=received.timestamp()<=min(close+360,cutoff.timestamp()):
                raise ValueError()
        except (ValueError,KeyError,TypeError,AttributeError):
            rejects["invalid_or_late_receipt"]+=1;continue
        by_close.setdefault(close,[]).append(a)
    totals=Counter();reasons=Counter();results=[]
    for i in range(WARMUP-1,len(m5)):
        close=m5[i]["t"]+300
        prefixes={tf:{"status":"ok","bars":[b for b in bars if b["t"]+STEPS[tf]<=close]} for tf,bars in frames.items()}
        if any(len(f["bars"])<WARMUP for f in prefixes.values()):continue
        now=stamp(close)
        prefix={"source":VENUE,"status":"verified","collected_at_utc":now.isoformat(),"timeframes":prefixes}
        # Revalidate genuine raw alerts against causal prefixes; no synthetic TV evidence.
        obs=[]
        for a in by_close.get(close,[]):
            record=evaluate_event(a,prefix,now)
            if record["status"]=="observed_not_trade":
                if record["event_id"] not in {x["event_id"] for x in obs}:obs.append(record)
            else:rejects.update(record["reasons"])
        report["bars_evaluated"]+=1
        report["matched_alerts"]+=len(obs)
        report["bars_with_matched_alert"]+=bool(obs)
        r=gate(prefix,obs,now)
        totals.update({k:v for k,v in r["diagnostics"].items() if k!="latest_m5_close_s" and type(v) is int})
        reasons.update(r["reasons"])
        for e in r["paper_entries"]:
            future=[{**b,"t":b["t"]+300,"closed":True} for b in m5[i+1:]]
            simulated=compare_rr_paths(e["direction"],e["entry"],e["stop_loss"],close,future,total_cost_bps=e["total_cost_bps"])
            results.append({"historical_id":e["entry_id"],"direction":e["direction"],"entry_close_utc":close,
                "entry":e["entry"],"stop_loss":e["stop_loss"],"liquidity_target":e["take_profit"],
                "classification":"historical_counterfactual_not_forward_entry","outcomes":simulated["outcomes"]})
    report.update(status="evaluated" if report["bars_evaluated"] else "insufficient_data",
        funnel=dict(totals),reasons=dict(reasons),alert_rejections=dict(rejects),
        historical_hypotheses=results,statistics=aggregate(results),
        by_direction={d:aggregate([e for e in results if e["direction"]==d]) for d in ("long","short")})
    return report

def main():
    snapshot=json.loads((DATA/"BTC-okx-futures-candles.json").read_text())
    alerts=[json.loads(line) for line in (DATA/"BTC-tradingview-events.jsonl").read_text().splitlines() if line.strip()]
    r=replay(snapshot,alerts)
    OUT.write_text(json.dumps(r,indent=2)+"\n")
    print("REPLAY SUMMARY",json.dumps({k:v for k,v in r.items() if k not in ("historical_hypotheses","statistics","by_direction")}))
    print("REPLAY HYPOTHESES",len(r["historical_hypotheses"]))
if __name__=="__main__":main()
