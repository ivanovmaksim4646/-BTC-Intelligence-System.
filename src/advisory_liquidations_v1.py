"""Independent public liquidation provider probe. No signal integration."""
import datetime as dt
import json, math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request,urlopen
from urllib.error import HTTPError

SOURCES={
 "swole_estimated_heatmap":"https://swolecharts.com/api/liquidation-heatmap/BTC?range=24h",
 "swole_estimated_levels":"https://swolecharts.com/api/liquidation-levels/BTC?range=24h",
 "smart_down":"https://api.smartmoneyapi.com/v1/liquidations/simulate?symbol=BTC&move_pct=-5",
 "smart_up":"https://api.smartmoneyapi.com/v1/liquidations/simulate?symbol=BTC&move_pct=5",
 "smart_realized":"https://api.smartmoneyapi.com/v1/liquidations/heatmap?symbol=BTC&window_minutes=240",
}
def valid_num(x):return type(x) in (float,int) and math.isfinite(x)
def smart_sim(raw,move):
    if raw.get("ok") is not True or raw.get("estimated") is not True or raw.get("symbol")!="BTC" or raw.get("empty"):return {"status":"unavailable"}
    p,t=raw.get("current_price"),raw.get("target_price")
    if not valid_num(p) or p<=0 or not valid_num(t) or t<=0 or raw.get("move_pct")!=move or abs(t/p-1-move/100)>.001:raise ValueError("invalid scenario")
    rows=raw.get("clusters")
    if not isinstance(rows,list):raise ValueError("missing clusters")
    side="long" if move<0 else "short";levels=[]
    for x in rows:
        price,usd=x.get("price"),x.get("notional_usd")
        if x.get("side")!=side or not valid_num(price) or price<=0 or not valid_num(usd) or usd<0:raise ValueError("invalid cluster")
        if not min(p,t)<=price<=max(p,t):raise ValueError("cluster outside simulated move")
        levels.append({"price":price,"side":side.upper(),"estimated_usd":usd,"whale_usd":x.get("whale_usd"),"oi_usd":x.get("oi_usd")})
    return {"status":"provider_estimate" if levels else "empty_unverified","classification":"hypothetical_move_not_observed_positions",
            "price":p,"target_price":t,"move_pct":move,"clusters":levels,"source_timestamp_verified":False}
def smart_realized(raw):
    if raw.get("symbol")!="BTC" or raw.get("window_minutes")!=240 or raw.get("source")=="unavailable":return {"status":"unavailable"}
    rows=raw.get("clusters")
    if not isinstance(rows,list):raise ValueError("invalid realized clusters")
    for x in rows:
        if not all(valid_num(x.get(k)) and x[k]>=0 for k in ("price","notional","long_notional","short_notional","count")):raise ValueError("invalid realized row")
    return {"status":"provider_observed_partial" if rows else "empty_unverified",
            "classification":"provider_reported_executed_liquidations","clusters":rows,"coverage":raw.get("coverage"),
            "generated_at":raw.get("generated_at"),"totals":raw.get("totals"),"exchanges":raw.get("exchanges")}
def collect(item):
    name,url=item
    out={"source_url":url,"status":"unavailable","classification":"provider_raw_unverified"}
    try:
        with urlopen(Request(url,headers={"User-Agent":"BTC-Intelligence/1.0","Accept":"application/json"}),timeout=15) as response:
            data=response.read(12_000_001)
            if len(data)>12_000_000:raise ValueError("oversized_response")
            raw=json.loads(data)
        if not isinstance(raw,dict):raise ValueError("unexpected envelope")
        out["schema_keys"]=sorted(raw)
        out["schema_shapes"]={k:{"type":type(v).__name__,"length":len(v) if isinstance(v,(list,dict)) else None,
                                 "first":str(v[0])[:350] if isinstance(v,list) and v else None} for k,v in raw.items()}
        out["raw"]=raw
        if name=="smart_down":out.update(smart_sim(raw,-5))
        elif name=="smart_up":out.update(smart_sim(raw,5))
        elif name=="smart_realized":out.update(smart_realized(raw))
        else:
            # Swole schema first verified in actual CI, never promote a generic 200 response.
            out.update(status="schema_probe_only",classification="estimated_provider_payload_pending_validation")
    except HTTPError as e:out["error"]="HTTP "+str(e.code)
    except Exception as e:out["error"]=type(e).__name__+": "+str(e)[:150]
    out["received_at_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    return name,out
def main():
    with ThreadPoolExecutor(max_workers=3) as pool:sources=dict(pool.map(collect,SOURCES.items()))
    doc={"classification":"advisory_only","generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
         "sources":sources,"trade_signal":None,"limitations":["Providers are not independent if they use overlapping OI or venues; never sum their estimates.","No provider estimate is a verified liquidation order.","Source timestamps must be validated before production use."]}
    Path("data/BTC-advisory-liquidations-v1.json").write_text(json.dumps(doc,allow_nan=False))
    for k,v in sources.items():
        print(k,json.dumps({x:y for x,y in v.items() if x not in ("raw","clusters")},allow_nan=False)[:6500])
if __name__=="__main__":main()
