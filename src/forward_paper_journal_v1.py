"""Prospective paper journal; previews never imply an executed fill."""
import datetime as dt
import math,json,hashlib
from pathlib import Path
from src.okx_outcome_tracker_v1 import check_bar,read_jsonl,VENUE
from src.okx_confluence_v2 import fresh
from src.okx_market_context_v1 import fresh_structure_break
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
    episode=p.get("episode_id")
    if any(x.get("id")==ident or (episode is not None and x.get("episode_id")==episode) for x in rows):return None
    managed=p.get("management")=="fta_or_ltf_shift_be_v1"
    fta=p.get("fta")
    if managed and (type(fta) not in (int,float) or not math.isfinite(fta) or not (e<fta<=t if d=="long" else t<=fta<e)):return None
    equity=1000+sum(x.get("pnl_usd",0) for x in rows if x.get("status") in ("win","loss","be"))
    if equity<=0:return None
    qty=min(equity*.01/risk,equity*5/e)
    start=(int(now.timestamp())//300+1)*300
    return {"id":ident,"source":VENUE,"direction":d,"issued_at_utc":now.isoformat(),"eligible_from":start,"expires_at":start+900,"entry":e,"stop_loss":s,"take_profit":t,"cost_bps":c,"quantity_btc":qty,"risk_usd":qty*risk,"status":"pending","paper_only":True,"last_processed":start-300,
            **({"episode_id":episode} if episode is not None else {}),
            **({"fta":fta,"fta_kind":p.get("fta_kind"),"management":p["management"],"active_stop_loss":s,"be_trigger":None} if managed else {})}
def favorable_shift(bars,i,fill_bar,direction):
    # At close only. Do not compute a shift across a missing M5 interval.
    recent=bars[max(0,i-119):i+1]
    if len(recent)<12 or any(not check_bar(b) for b in recent):return False
    if any(v["t"]-u["t"]!=300 for u,v in zip(recent,recent[1:])):return False
    if recent[-1]["t"]<=fill_bar:return False
    event=fresh_structure_break(recent,"5m")
    return bool(event and event.get("kind")==("bullish_shift_candidate" if direction=="long" else "bearish_shift_candidate"))

def advance(row,bars,now):
    r=dict(row)
    if r["status"] not in ("pending","open"):return r
    managed=r.get("management")=="fta_or_ltf_shift_be_v1"
    for i,b in enumerate(bars):
        if not check_bar(b):raise ValueError("invalid bar")
        t=b["t"]
        if t<=r["last_processed"] or t+300>now.timestamp():continue
        if t!=r["last_processed"]+300:
            r["status"]="censored_gap";return r
        r["last_processed"]=t
        e,p=r["entry"],r["take_profit"]
        s=r.get("active_stop_loss",r["stop_loss"])
        long=r["direction"]=="long"
        stop=b["l"]<=s if long else b["h"]>=s
        target=b["h"]>=p if long else b["l"]<=p
        fta_hit=managed and (b["h"]>=r["fta"] if long else b["l"]<=r["fta"])
        if r["status"]=="pending":
            if t>=r["expires_at"]:
                r["status"]="expired";return r
            entry_hit=b["l"]<=e<=b["h"]
            if managed and not entry_hit and (fta_hit or stop):
                r.update(status="cancelled",cancel_reason="fta_before_entry" if fta_hit else "stop_before_entry");return r
            if not entry_hit:continue
            if stop or target or fta_hit:
                r["status"]="censored_entry_bar";return r
            r["status"]="open";r["fill_bar"]=t;continue
        if stop and target:
            r["status"]="censored_same_bar";return r
        if stop or target:
            # The stop effective at the OPEN of this bar applies. A new BE
            # trigger at this close cannot retroactively prevent a loss.
            exit_price=(min(s,b["o"]) if long else max(s,b["o"])) if stop else p
            pnl=r["quantity_btc"]*((exit_price-e)*(1 if long else -1)-e*r["cost_bps"]/10000)
            status="win" if target else ("be" if r.get("be_trigger") and exit_price==e else "loss")
            r.update(status=status,exit_price=exit_price,closed_at=t+300,pnl_usd=pnl,r_multiple=pnl/r["risk_usd"])
            return r
        if managed and not r.get("be_trigger"):
            # Move to nominal entry only from the NEXT candle. Costs still
            # count; a gap through entry is a loss, not an assumed BE fill.
            trigger="fta_test" if fta_hit else ("m5_shift" if favorable_shift(bars,i,r["fill_bar"],r["direction"]) and (b["c"]>e if long else b["c"]<e) else None)
            if trigger:
                r.update(active_stop_loss=e,be_trigger=trigger,be_effective_from=t+300)
    return r
def stats(rows):
    wins=[x for x in rows if x["status"]=="win"];losses=[x for x in rows if x["status"]=="loss"];be=[x for x in rows if x["status"]=="be"];closed=wins+losses+be
    pnl=sum(x["pnl_usd"] for x in closed)
    return {"initial_equity_usd":1000,"equity_usd":1000+pnl,"wins":len(wins),"losses":len(losses),"be":len(be),"win_rate_pct":100*len(wins)/(len(wins)+len(losses)) if wins or losses else None,"pnl_usd":pnl,"pnl_pct":pnl/10,"total_r":sum(x["r_multiple"] for x in closed),"open":sum(x["status"]=="open" for x in rows),"pending":sum(x["status"]=="pending" for x in rows),"censored":sum(x["status"].startswith("censored") for x in rows),"expired":sum(x["status"]=="expired" for x in rows),"cancelled":sum(x["status"]=="cancelled" for x in rows)}
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
