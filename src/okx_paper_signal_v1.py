"""Fail-closed paper signal admission; no real orders or inferred probabilities."""
import datetime as dt
import json
import math
from pathlib import Path
from src.okx_confluence_v2 import fresh, VENUE
DATA=Path("data")
def evaluate(confluence, gate, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    out={"generated_at_utc":now.isoformat(),"source":VENUE,"classification":"paper_signal_preview_only",
         "decision":"NO_TRADE","paper_signal":None,"execution_enabled":False,"reasons":[]}
    def reject(reason):
        out["reasons"].append(reason)
        return out
    if not isinstance(confluence,dict) or not isinstance(gate,dict):
        return reject("missing_inputs")
    if (confluence.get("source")!=VENUE or gate.get("source")!=VENUE
        or confluence.get("classification")!="okx_confluence_research_only"
        or gate.get("classification")!="independently_reconstructed_okx_paper_hypotheses"
        or not fresh(confluence.get("generated_at_utc"),now)
        or not fresh(gate.get("generated_at_utc"),now)):
        return reject("unverified_or_stale_inputs")
    close=confluence.get("m5_close_s")
    if type(close) is not int or not 0<=now.timestamp()-close<=420 or close!=(gate.get("diagnostics") or {}).get("latest_m5_close_s"):
        return reject("unsynchronized_setup")
    if confluence.get("missing") or confluence.get("conflicts"):
        return reject("incomplete_or_conflicting_evidence")
    direction=confluence.get("watch_direction")
    if direction not in ("long","short"):
        return reject("no_aligned_direction")
    candidates=[]
    for p in gate.get("structural_research",[]):
        if p.get("direction")!=direction or p.get("entry_close_utc")!=close or p.get("status")!="paper_candidate":
            continue
        e,s,t,c=(p.get(k) for k in ("entry","stop_loss","take_profit","cost_bps"))
        if not all(type(x) in (int,float) and math.isfinite(x) and x>0 for x in (e,s,t,c)):
            continue
        if not (s<e<t if direction=="long" else t<e<s):
            continue
        rr=(abs(t-e)-e*c/10000)/(abs(e-s)+e*c/10000)
        if rr<2:continue
        candidates.append({**p,"rr_net_estimate":rr})
    if not candidates:return reject("no_structural_setup_net_rr_two")
    # Choose nearest verified target; never select a more distant target to improve RR.
    p=min(candidates,key=lambda x:(abs(x["take_profit"]-x["entry"]),-abs(x["entry"]-x["stop_loss"])))
    out["decision"]=direction.upper()
    out["paper_signal"]={**p,"paper_only":True,"risk_fraction_cap":0.01,"leverage_cap":5}
    return out
def main():
    def read(name):
        try:return json.loads((DATA/name).read_text())
        except (OSError,ValueError):return {}
    r=evaluate(read("BTC-okx-confluence-v2.json"),read("BTC-okx-entry-evidence-gate-v1.json"))
    p=DATA/"BTC-okx-paper-signal-v1.json";tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(r,indent=2)+"\n");tmp.replace(p)
    print("Paper signal preview",r["decision"],r["reasons"])
if __name__=="__main__":main()
