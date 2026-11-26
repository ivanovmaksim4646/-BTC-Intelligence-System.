"""OKX-only evidence integration. Observational watch, never an executed signal."""
import json,datetime as dt,math
from pathlib import Path
from decimal import Decimal
DATA=Path("data")
VENUE="OKX BTC-USDT-SWAP"
def obj(x):return x if isinstance(x,dict) else {}
def fresh(x,now,limit=900):
    try:
        t=dt.datetime.fromisoformat(x.replace("Z","+00:00"))
        return t.utcoffset() is not None and 0<=(now-t).total_seconds()<=limit
    except (ValueError,TypeError,AttributeError):return False
def direction(x):
    return {"bullish":"long","bearish":"short"}.get(x)
def window(flow,inst,tf,close):
    if flow.get("classification")!="volume_reconciled_rest_research_only" or flow.get("end_ms")!=close*1000:return None
    w=obj(obj(obj(obj(flow.get("instruments")).get(inst)).get("rolling_windows")).get(tf))
    n={"5m":1,"15m":3,"1h":12,"4h":48}[tf]
    if w.get("coverage")!="volume_reconciled_not_sequence_certified" or w.get("end_ms")!=close*1000 or w.get("start_ms")!=(close-n*300)*1000 or w.get("required_m5")!=n or w.get("reconciled_m5")!=n:return None
    try:
        d=Decimal(str(w["delta_btc_reconciled"]));v=Decimal(str(w["volume_btc_reconciled"]))
        if not d.is_finite() or not v.is_finite() or v<abs(d):return None
        return {"delta_btc":str(d),"volume_btc":str(v),"direction":"long" if d>0 else "short" if d<0 else "neutral","quality":"volume_reconciled_not_sequence_certified"}
    except (ArithmeticError,KeyError,ValueError):return None
def evaluate(context,gate,flow,derivatives,now=None,external=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.utcoffset() is None:raise ValueError("timezone required")
    context,gate,flow,derivatives=map(obj,(context,gate,flow,derivatives))
    out={"classification":"okx_confluence_research_only","source":VENUE,"generated_at_utc":now.isoformat(),
        "decision":"NO_TRADE","trade_signal":None,"execution_ready":False,"directional_probability":None,
        "watch_direction":None,"support":[],"conflicts":[],"missing":[],"flow":{},"structure":{},"derivatives":None,"liquidity":None,"macro":None,"breadth":None,"liquidation_heatmap":None,"paper_candidates":[]}
    missing=out["missing"]
    missing.extend(["macro","breadth","liquidation_heatmap"])
    external=obj(external)
    breadth=obj(external.get("breadth"))
    vals=[breadth.get(k) for k in ("btc_d_pct","total_usd","total_ex_btc_usd","total_ex_btc_eth_usd")]
    if (breadth.get("source")=="CoinGecko global"
        and breadth.get("classification")=="provider_universe_proxies_not_tradingview_indices"
        and fresh(breadth.get("asof_utc"),now,1800)
        and all(type(v) in (int,float) and math.isfinite(v) for v in vals)
        and 0<vals[0]<100 and vals[1]>vals[2]>vals[3]>0):
        out["breadth"]=breadth
        missing.remove("breadth")
    # Monthly observations alone do not establish event risk or consensus.
    out["macro"]=obj(external.get("macro")) or None
    out["macro_status"]=external.get("macro_status","unavailable")
    if context.get("source")!=VENUE or context.get("classification")!="closed_okx_swing_structure_plus_sampled_liquidity_research" or not fresh(context.get("generated_at_utc"),now):
        missing.append("fresh_verified_structure");return out
    frames=obj(context.get("timeframes"));m5=obj(frames.get("5m"))
    close=m5.get("last_closed_candle_close_s")
    if type(close) is not int or close%300 or not 0<=now.timestamp()-close<=420:
        missing.append("fresh_m5_close");return out
    out["m5_close_s"]=close
    for tf,step in (("5m",300),("15m",900),("1h",3600),("4h",14400)):
        frame=obj(frames.get(tf));t=frame.get("last_closed_candle_close_s")
        state=frame.get("structure")
        if frame.get("status")=="observed" and type(t) is int and t%step==0 and 0<=close-t<step and state in ("bullish","bearish","mixed","insufficient_pivots"):
            out["structure"][tf]=state
        else:missing.append("structure_"+tf)
    s=out["structure"];h=direction(s.get("1h"));l=direction(s.get("5m"))
    h=h if h and h==direction(s.get("4h")) else None
    l=l if l and l==direction(s.get("15m")) else None
    if h and l and h!=l:out["conflicts"].append("htf_ltf_disagreement")
    if h and h==l:out["support"].append("htf_ltf_aligned")
    for tf in ("5m","15m","1h","4h"):
        a=window(flow,"BTC-USDT",tf,close);b=window(flow,"BTC-USDT-SWAP",tf,close)
        out["flow"][tf]={"spot":a,"futures":b}
        if not a or not b:missing.append("reconciled_flow_"+tf)
        elif a["direction"]!=b["direction"]:out["conflicts"].append("spot_futures_disagree_"+tf)
    a=out["flow"]["5m"]["spot"];b=out["flow"]["5m"]["futures"]
    f=a["direction"] if a and b and a["direction"]==b["direction"] and a["direction"]!="neutral" else None
    if f and h and f!=h:out["conflicts"].append("m5_flow_vs_htf")
    if f and f==h==l:out["support"].append("reconciled_m5_flow_aligned")
    liq=obj(context.get("liquidity_context"));t=liq.get("book_timestamp_ms")
    if type(t) is int and 0<=now.timestamp()*1000-t<=900000 and abs(t-close*1000)<=420000 and liq.get("not_executed_volume") is True:
        out["liquidity"]={"resting_side":liq.get("resting_side"),"timestamp_ms":t,"interpretation":"cancellable_resting_orders_not_directional_vote"}
    else:missing.append("fresh_resting_liquidity")
    if derivatives.get("source")==VENUE and derivatives.get("classification")=="read_only_okx_snapshot_context" and fresh(derivatives.get("generated_at_utc"),now):
        out["derivatives"]={k:derivatives.get(k) for k in ("oi_change","funding","mark_index")}
        for k,v in out["derivatives"].items():
            if v is None:missing.append(k)
    else:missing.append("fresh_derivatives")
    if gate.get("source")==VENUE and gate.get("classification")=="independently_reconstructed_okx_paper_hypotheses" and fresh(gate.get("generated_at_utc"),now) and obj(gate.get("diagnostics")).get("latest_m5_close_s")==close:
        out["paper_candidates_count"]=gate.get("paper_entries_count",0)
        out["paper_candidates_status"]="gate_summary_only_not_entry_authorization"
    else:missing.append("fresh_entry_gate")
    # Direction is descriptive watch only. No votes from correlated indicators,
    # resting liquidity, or OI, and no fabricated macro or probability.
    if h and h==l==f and not out["conflicts"]:out["watch_direction"]=h
    return out
def main():
    def read(name):
        try:return json.loads((DATA/name).read_text())
        except (OSError,ValueError):return {}
    r=evaluate(read("BTC-okx-market-context-v1.json"),read("BTC-okx-entry-evidence-gate-v1.json"),read("BTC-okx-reconciled-flow-current.json"),read("BTC-okx-derivatives-context-v1.json"),external=read("BTC-market-breadth-macro-v1.json"))
    DATA.mkdir(exist_ok=True)
    p=DATA/"BTC-okx-confluence-v2.json";t=p.with_suffix(".tmp");t.write_text(json.dumps(r,indent=2)+"\n");t.replace(p)
    print("OKX CONFLUENCE",json.dumps(r),flush=True)
if __name__=="__main__":main()
