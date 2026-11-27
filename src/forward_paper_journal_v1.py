"""Prospective paper journal; previews never imply an executed fill."""
import datetime as dt
import math,json,hashlib
from pathlib import Path
from src.okx_outcome_tracker_v1 import check_bar,read_jsonl,VENUE
from src.okx_confluence_v2 import fresh
DATA=Path("data")
def admit(preview,rows,now,enabled=False):
    if not enabled or preview.get("source")!=VENUE or preview.get("classification")!="paper_signal_preview_only" or preview.get("execution_enabled") is not False or not fresh(preview.get("generated_at_utc"),now,120):return None
    p=preview.get("paper_signal") or {}
    d=p.get("direction")
    if d not in ("long","short") or preview.get("decision")!=d.upper() or p.get("paper_only") is not True:return None
    if any(x.get("status") in ("pending","open") for x in rows):return None
    e,s,t,c=[p.get(k) for k in ("entry","stop_loss","take_profit","cost_bps")]
    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (e,s,t,c)):return None
    if not (s<e<t if d=="long" else t<e<s):return None
    cost=e*c/10000;risk=abs(e-s)+cost
    if (abs(t-e)-cost)/risk<2:return None
    close=p.get("entry_close_utc")
    if type(close) is not int or close%300 or not 0<=now.timestamp()-close<=420:return None
    ident=hashlib.sha256(f"{VENUE}:{close}:{d}".encode()).hexdigest()[:24]
    if any(x.get("id")==ident for x in rows):return None
    equity=1000+sum(x.get("pnl_usd",0) for x in rows if x.get("status") in ("win","loss"))
    if equity<=0:return None
    qty=min(equity*.01/risk,equity*5/e)
    start=(int(now.timestamp())//300+1)*300
    return {"id":ident,"source":VENUE,"direction":d,"issued_at_utc":now.isoformat(),"eligible_from":start,"expires_at":start+900,"entry":e,"stop_loss":s,"take_profit":t,"cost_bps":c,"quantity_btc":qty,"risk_usd":qty*risk,"status":"pending","paper_only":True,"last_processed":start-300}
def advance(row,bars,now):
    r=dict(row)
    if r["status"] not in ("pending","open"):return r
    for b in bars:
        if not check_bar(b):raise ValueError("invalid bar")
        t=b["t"]
        if t<=r["last_processed"] or t+300>now.timestamp():continue
        if t!=r["last_processed"]+300:
            r["status"]="censored_gap";return r
        r["last_processed"]=t
        e,s,p=r["entry"],r["stop_loss"],r["take_profit"]
        long=r["direction"]=="long"
        stop=b["l"]<=s if long else b["h"]>=s
        target=b["h"]>=p if long else b["l"]<=p
        if r["status"]=="pending":
            if t>=r["expires_at"]:
                r["status"]="expired";return r
            if not b["l"]<=e<=b["h"]:continue
            if stop or target:
                r["status"]="censored_entry_bar";return r
            r["status"]="open";r["fill_bar"]=t;continue
        if stop and target:
            r["status"]="censored_same_bar";return r
        if stop or target:
            # Gap beyond stop uses the adverse open, not the ideal stop.
            exit_price=(min(s,b["o"]) if long else max(s,b["o"])) if stop else p
            pnl=r["quantity_btc"]*((exit_price-e)*(1 if long else -1)-e*r["cost_bps"]/10000)
            r.update(status="loss" if stop else "win",exit_price=exit_price,closed_at=t+300,pnl_usd=pnl,r_multiple=pnl/r["risk_usd"])
            return r
    return r
def stats(rows):
    wins=[x for x in rows if x["status"]=="win"];losses=[x for x in rows if x["status"]=="loss"];closed=wins+losses
    pnl=sum(x["pnl_usd"] for x in closed)
    return {"initial_equity_usd":1000,"equity_usd":1000+pnl,"wins":len(wins),"losses":len(losses),"win_rate_pct":100*len(wins)/len(closed) if closed else None,"pnl_usd":pnl,"pnl_pct":pnl/10,"total_r":sum(x["r_multiple"] for x in closed),"open":sum(x["status"]=="open" for x in rows),"pending":sum(x["status"]=="pending" for x in rows),"censored":sum(x["status"].startswith("censored") for x in rows),"expired":sum(x["status"]=="expired" for x in rows)}
def main():
    # User-authorized prospective simulation only; preview quality gates remain mandatory.
    enabled=True
    now=dt.datetime.now(dt.timezone.utc)
    journal=DATA/"BTC-forward-paper-journal-v1.json"
    rows=json.loads(journal.read_text()) if journal.exists() else []
    bars,bad=read_jsonl(DATA/"BTC-okx-m5-closed-history-v1.jsonl")
    if bad:raise ValueError("corrupt archive")
    rows=[advance(x,bars,now) for x in rows]
    preview_path=DATA/"BTC-okx-paper-signal-v1.json"
    preview=json.loads(preview_path.read_text()) if preview_path.exists() else {}
    candidate=admit(preview,rows,now,enabled=enabled)
    if candidate:rows.append(candidate)
    for path,value in ((journal,rows),(DATA/"BTC-forward-paper-statistics-v1.json",{"generated_at_utc":now.isoformat(),"admission_enabled":enabled,**stats(rows)})):
        tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(value,indent=2)+"\n");tmp.replace(path)
if __name__=="__main__":main()
