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
def fresh_epoch(value,now,max_age=900):
    if not valid_num(value) or value<=0:return None
    sec=value/1000 if value>1e11 else value
    return sec if -30<=now.timestamp()-sec<=max_age else None
def smart_sim(raw,move,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if raw.get("ok") is not True or raw.get("estimated") is not True or raw.get("symbol")!="BTC" or raw.get("empty"):return {"status":"unavailable"}
    p,t=raw.get("current_price"),raw.get("target_price")
    if not valid_num(p) or p<=0 or not valid_num(t) or t<=0 or raw.get("move_pct")!=move or abs(t/p-1-move/100)>.001:raise ValueError("invalid scenario")
    rows=raw.get("clusters")
    if not isinstance(rows,list):raise ValueError("missing clusters")
    side="long" if move<0 else "short";levels=[];excluded=0
    stamp=fresh_epoch(raw.get("ts"),now)
    age=raw.get("study_age_s")
    if stamp is None or not valid_num(age) or not 0<=age<=900:return {"status":"stale_or_unverified"}
    for x in rows:
        price,usd=x.get("price"),x.get("notional_usd")
        if x.get("side") not in ("long","short") or not valid_num(price) or price<=0 or not valid_num(usd) or usd<0:raise ValueError("invalid cluster")
        if x["side"]!=side or not min(p,t)<=price<=max(p,t):
            excluded+=1;continue
        levels.append({"price":price,"side":side.upper(),"estimated_usd":usd,"whale_usd":x.get("whale_usd"),"oi_usd":x.get("oi_usd")})
    return {"status":"provider_estimate" if levels else "empty_unverified","classification":"hypothetical_move_not_observed_positions",
            "price":p,"target_price":t,"move_pct":move,"clusters":levels,"source_timestamp_verified":True,"provider_as_of_epoch_s":stamp,"study_age_s":age,"excluded_outside_scenario":excluded,"total_estimated_crossed_usd":sum(x["estimated_usd"] for x in levels)}
def smart_realized(raw,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if raw.get("symbol")!="BTC" or raw.get("window_minutes")!=240 or raw.get("source")=="unavailable":return {"status":"unavailable"}
    rows=raw.get("clusters")
    if not isinstance(rows,list):raise ValueError("invalid realized clusters")
    if fresh_epoch(raw.get("generated_at"),now) is None:return {"status":"stale_or_unverified"}
    for x in rows:
        if not all(valid_num(x.get(k)) and x[k]>=0 for k in ("price","notional","long_notional","short_notional","count")):raise ValueError("invalid realized row")
    return {"status":"provider_observed_partial" if rows else "empty_unverified",
            "classification":"provider_reported_executed_liquidations","clusters":rows,"coverage":raw.get("coverage"),
            "generated_at":raw.get("generated_at"),"totals":raw.get("totals"),"exchanges":raw.get("exchanges"),"exchanges_contributed":raw.get("exchanges_contributed")}
def swole(raw,kind,now):
    if raw.get("coin")!="BTC" or not valid_num(raw.get("price")) or raw["price"]<=0:return {"status":"invalid"}
    stamp=fresh_epoch(raw.get("as_of"),now)
    if stamp is None:return {"status":"stale_or_unverified"}
    out={"classification":"provider_modeled_liquidation_estimate_not_actual_positions","provider_as_of_epoch_s":stamp,"price":raw["price"]}
    if kind=="levels":
        if raw.get("estimated") is not True or raw.get("has_data") is not True or not raw.get("model_version"):return {"status":"unavailable"}
        levels=raw.get("levels");totals=raw.get("totals")
        if not isinstance(levels,dict) or not levels or not isinstance(totals,list) or not totals:return {"status":"invalid"}
        for row in totals:
            if not all(valid_num(row.get(k)) and row[k]>=0 for k in ("pct","long_usd","short_usd")) or not 0<row["pct"]<=1:return {"status":"invalid"}
        return dict(out,status="provider_estimate",model_version=raw["model_version"],totals=totals,level_keys=sorted(levels),level_sample={k:str(v)[:450] for k,v in levels.items()})
    if raw.get("error") is not False or raw.get("db") is not True or raw.get("price_stale") is not False:return {"status":"unavailable_or_stale"}
    if fresh_epoch(raw.get("price_as_of"),now) is None:return {"status":"stale_or_unverified"}
    rows,cols=raw.get("rows"),raw.get("cols")
    if type(rows) is not int or type(cols) is not int or not 0<rows*cols<=10_000_000 or min(rows,cols)<=0:return {"status":"invalid"}
    if not isinstance(raw.get("cells"),str) or not raw["cells"] or not raw.get("model"):return {"status":"invalid"}
    return dict(out,status="fresh_encoded_grid_pending_decode",rows=rows,cols=cols,model=raw["model"],encoded_length=len(raw["cells"]))
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
        out["schema_shapes"].update({k:{"type":type(raw[k]).__name__,"value":raw[k]} for k in ("as_of","ts","study_age_s","generated_at","price_stale","db","error","price_as_of") if k in raw})
        if name=="smart_down":out.update(smart_sim(raw,-5))
        elif name=="smart_up":out.update(smart_sim(raw,5))
        elif name=="smart_realized":out.update(smart_realized(raw))
        else:
            out.update(swole(raw,"levels" if name.endswith("levels") else "heatmap",dt.datetime.now(dt.timezone.utc)))
    except HTTPError as e:out["error"]="HTTP "+str(e.code)
    except Exception as e:out["error"]=type(e).__name__+": "+str(e)[:150]
    out["received_at_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
    return name,out
def main():
    with ThreadPoolExecutor(max_workers=3) as pool:sources=dict(pool.map(collect,SOURCES.items()))
    doc={"classification":"advisory_only","generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
         "sources":sources,"trade_signal":None,"limitations":["Providers are not independent if they use overlapping OI or venues; never sum their estimates.","No provider estimate is a verified liquidation order.","Provider timestamps checked at collection; reports must recheck age. Encoded grid and individual level schema not yet decoded."]}
    Path("data/BTC-advisory-liquidations-v1.json").write_text(json.dumps(doc,allow_nan=False))
    for k,v in sources.items():
        print(k,json.dumps({x:y for x,y in v.items() if x not in ("raw","clusters")},allow_nan=False)[:6500])
if __name__=="__main__":main()
