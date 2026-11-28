"""Advisory context only. No imports from or writes to signal/journal modules."""
import datetime as dt
import json, math
from pathlib import Path
from src.market_breadth_macro_v1 import fetch
from src.report_feed import timestamp
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

DATA=Path("data")
def read(name):
    try:return json.loads((DATA/name).read_text())
    except (OSError,ValueError):return {}
def positive(v):
    return type(v) in (int,float) and math.isfinite(v) and v>0
def breadth(doc,now):
    b=doc.get("breadth") or {}
    t=timestamp(b.get("asof_utc"))
    keys=("btc_d_pct","total_usd","total_ex_btc_usd","total_ex_btc_eth_usd")
    if not t or not 0<=(now-t).total_seconds()<=1800 or not all(positive(b.get(k)) for k in keys):
        return {"status":"missing_or_stale"}
    if not 0<b["btc_d_pct"]<100 or not b["total_usd"]>b["total_ex_btc_usd"]>b["total_ex_btc_eth_usd"]:return {"status":"invalid"}
    return {"status":"observed",**b}
def volatility(raw,now):
    result=raw.get("result") or []
    rows=result.get("data",[]) if isinstance(result,dict) else result
    if not rows:return {"status":"unavailable"}
    row=max(rows,key=lambda x:x[0])
    t,v=row[0],row[4]
    if not positive(t) or not positive(v) or not 0<=now.timestamp()*1000-t<=7200000:return {"status":"stale_or_invalid"}
    return {"status":"observed","source":"Deribit DVOL BTC","timestamp_ms":t,"annualized_implied_volatility_pct":v,
            "classification":"30_day_options_implied_volatility_not_BVOL24"}
def stablecoins(raw,now):
    if not isinstance(raw,list):raise ValueError("invalid markets")
    out={}
    for row in raw:
        key=row.get("id")
        if key not in ("tether","usd-coin"):continue
        stamp=timestamp(row.get("last_updated"))
        cap,supply=row.get("market_cap"),row.get("circulating_supply")
        if stamp and 0<=(now-stamp).total_seconds()<=1800 and positive(cap) and positive(supply):
            out[key]={"market_cap_usd":cap,"circulating_supply":supply,"asof_utc":stamp.isoformat()}
    return out
def reconciled_coverage(doc,now):
    end=doc.get("end_ms")
    out={"status":"missing_or_stale","sequence_certified":False,"instruments":{}}
    if type(end) is not int or end%300000 or not 0<=now.timestamp()*1000-end<=900000:return out
    for name in ("BTC-USDT","BTC-USDT-SWAP"):
        item=(doc.get("instruments") or {}).get(name) or {}
        windows={}
        for tf,n in (("5m",1),("15m",3),("1h",12),("4h",48)):
            w=(item.get("rolling_windows") or {}).get(tf) or {}
            if w.get("end_ms")!=end or w.get("required_m5")!=n or w.get("reconciled_m5")!=n:continue
            if w.get("start_ms")!=end-n*300000:continue
            try:
                delta=float(w["delta_btc_reconciled"]);volume=float(w["volume_btc_reconciled"])
            except (KeyError,ValueError,TypeError):continue
            if not math.isfinite(delta) or not math.isfinite(volume) or volume<abs(delta):continue
            windows[tf]={"delta_btc_reconciled":delta,"volume_btc":volume,"coverage":"volume_reconciled_not_sequence_certified"}
        out["instruments"][name]=windows
    out.update(status="observed_partial_or_complete",end_ms=end)
    return out

ETF_URL="https://farside.co.uk/btc/"
class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[];self.row=None;self.cell=None;self.table=0;self.table_id=0
    def handle_starttag(self,tag,attrs):
        if tag=="table":self.table+=1;self.table_id+=1
        if not self.table:return
        if tag=="tr":self.row=[]
        if tag in ("td","th") and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()));self.cell=None
        if tag=="tr" and self.row is not None:
            self.rows.append((self.table_id,self.row));self.row=None
        if tag=="table" and self.table:self.table-=1
def etf_flows(html,now):
    parser=Tables();parser.feed(html)
    headers={};rows={}
    local=now.astimezone(ZoneInfo("America/New_York"))
    def number(s):
        s=s.strip().replace(",","").replace("−","-")
        if s.startswith("(") and s.endswith(")"):s="-"+s[1:-1]
        try:v=float(s);return v if math.isfinite(v) else None
        except ValueError:return None
    for table,r in parser.rows:
        if len(r)>4 and r[-1].strip().lower()=="total" and "IBIT" in r and "FBTC" in r:
            headers[table]=r;continue
        h=headers.get(table)
        if not h or len(r)!=len(h):continue
        try:d=dt.datetime.strptime(r[0],"%d %b %Y").date()
        except ValueError:continue
        if d>=local.date() or d.weekday()>4:continue
        values=[number(s) for s in r[1:]]
        if values[-1] is None:continue
        # A dash is unknown, not zero; keep only fully numeric rows.
        if any(v is None for v in values):continue
        if abs(sum(values[:-1])-values[-1])>.05*len(values)+.01:continue
        record={"session_date_us":str(d),"net_flow_usd_m":values[-1],"funds_usd_m":dict(zip(h[1:-1],values[:-1]))}
        if d in rows and rows[d]!=record:raise ValueError("conflicting ETF rows")
        rows[d]=record
    recent=[rows[d] for d in sorted(rows)[-5:]]
    if not recent:return {"status":"unavailable","source":ETF_URL}
    age=(local.date()-dt.date.fromisoformat(recent[-1]["session_date_us"])).days
    return {"status":"observed" if age<=5 else "stale","source":ETF_URL,
            "classification":"provider_reported_daily_net_flows_usd_m_not_live_or_final_certified",
            "latest":recent[-1],"recent_sessions":recent,"calendar_days_old":age,
            "five_reported_sessions_usd_m":sum(r["net_flow_usd_m"] for r in recent) if len(recent)==5 else None}
def main():
    now=dt.datetime.now(dt.timezone.utc)
    out={"classification":"advisory_only","generated_at_utc":now.isoformat(),
         "breadth":breadth(read("BTC-market-breadth-macro-v1.json"),now),
         "stablecoins":{},"volatility":None,"errors":{},"trade_signal":None,
         "okx_flow_coverage":reconciled_coverage(read("BTC-okx-reconciled-flow-current.json"),now)}
    try:out["etf_flows"]=etf_flows(fetch(ETF_URL),now)
    except Exception as e:out["etf_flows"]={"status":"unavailable","source":ETF_URL};out["errors"]["etf_flows"]=type(e).__name__
    urls={"stablecoins":"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=tether,usd-coin",
          "volatility":"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp="+str(int(now.timestamp()*1000)-10800000)+"&end_timestamp="+str(int(now.timestamp()*1000))+"&resolution=3600"}
    for key,url in urls.items():
        try:
            raw=json.loads(fetch(url))
            out[key]=stablecoins(raw,now) if key=="stablecoins" else volatility(raw,now)
        except Exception as e:out["errors"][key]=type(e).__name__
    if out["breadth"]["status"]=="observed":
        for v in out["stablecoins"].values():
            v["dominance_pct_provider_proxy"]=100*v["market_cap_usd"]/out["breadth"]["total_usd"]
    out["limitations"]=["CoinGecko universe differs from TradingView TOTAL indices","DVOL is not BVOL24","No historical supply changes until validated prior snapshots exist","ETF latest numeric completed-date row only; no finality certification; liquidation heatmap unavailable"]
    p=DATA/"BTC-advisory-context-v1.json";tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n");tmp.replace(p)
    print(json.dumps(out,indent=2))
if __name__=="__main__":main()
