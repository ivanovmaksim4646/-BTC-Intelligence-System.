"""Public market breadth and official macro observations, no inferred consensus."""
import datetime as dt
import json, math, csv, io, urllib.request, os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
DATA=Path("data")
def fetch(url,headers=None):
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"BTC-Intelligence/1.0",**(headers or {})}),timeout=15) as r:
        return r.read().decode()
def breadth(raw,now):
    d=raw["data"]; total=d["total_market_cap"]["usd"]; p=d["market_cap_percentage"]; b=p["btc"]; e=p["eth"]; stamp=d["updated_at"]
    if not all(type(x) in (int,float) and math.isfinite(x) for x in (total,b,e,stamp)) or total<=0 or not 0<b<100 or not 0<e<100-b or not 0<=now.timestamp()-stamp<=1800:
        raise ValueError("invalid or stale global market data")
    return {"source":"CoinGecko global","asof_utc":dt.datetime.fromtimestamp(stamp,dt.timezone.utc).isoformat(),"btc_d_pct":b,
            "total_usd":total,"total_ex_btc_usd":total*(1-b/100),"total_ex_btc_eth_usd":total*(1-(b+e)/100),
            "classification":"provider_universe_proxies_not_tradingview_indices"}
def macro_series(raw,series,now):
    rows=list(csv.DictReader(io.StringIO(raw)))
    valid=[]
    for row in rows:
        try:
            date=dt.date.fromisoformat(row.get("observation_date",row.get("DATE","")))
            value=float(row[series])
            if math.isfinite(value) and date<=now.date():valid.append((date,value))
        except (ValueError,KeyError,TypeError):continue
    valid.sort()
    if len(valid)<2:raise ValueError("insufficient observations")
    a,b=valid[-2:]
    if (now.date()-b[0]).days>100:raise ValueError("stale monthly series")
    return {"source":"FRED","series":series,"observation_date":b[0].isoformat(),"actual":b[1],"previous":a[1],"previous_date":a[0].isoformat(),"consensus_forecast":None,"surprise":None}
def official_observations(rows,source,series,now,max_age):
    valid=sorted({date:float(value) for date,value in rows if date<=now.date() and math.isfinite(float(value))}.items())
    if len(valid)<2 or (now.date()-valid[-1][0]).days>max_age:raise ValueError("stale or incomplete")
    a,b=valid[-2:]
    return {"source":source,"series":series,"observation_date":b[0].isoformat(),"actual":b[1],"previous":a[1],"previous_date":a[0].isoformat(),"consensus_forecast":None,"surprise":None}
def bls(raw,series,now):
    if raw.get("status")!="REQUEST_SUCCEEDED":raise ValueError("BLS request failed")
    r=next(x for x in raw["Results"]["series"] if x["seriesID"]==series)
    rows=[(dt.date(int(x["year"]),int(x["period"][1:]),1),x["value"]) for x in r["data"] if x["period"] in {f"M{i:02}" for i in range(1,13)} and x["value"] not in ("-","")]
    return official_observations(rows,"BLS",series,now,100)
def effr(raw,now):
    rows=[(dt.date.fromisoformat(x["effectiveDate"]),x["percentRate"]) for x in raw["refRates"] if x.get("type")=="EFFR" and x.get("percentRate") is not None]
    return official_observations(rows,"New York Fed","EFFR_daily",now,7)
def main():
    now=dt.datetime.now(dt.timezone.utc)
    out={"generated_at_utc":now.isoformat(),"breadth":None,"macro":{},"errors":{},"trade_signal":None}
    key=os.getenv("COINGECKO_DEMO_API_KEY")
    try:out["breadth"]=breadth(json.loads(fetch("https://api.coingecko.com/api/v3/global",{"x-cg-demo-api-key":key} if key else {})),now)
    except Exception as exc:out["errors"]["breadth"]=type(exc).__name__
    series_map={"cpi_index":"CPIAUCSL","unemployment_pct":"UNRATE","payrolls_thousands":"PAYEMS","effective_fed_funds_pct":"FEDFUNDS","ppi_index":"PPIACO"}
    def get(item):
        name,series=item
        for url in ("https://fred.stlouisfed.org/graph/fredgraph.csv?id="+series,):
            try:
                raw=fetch(url)
                # Alternate mirrors must have the identical series identifier and dated observations.
                return name,macro_series(raw,series,now),None
            except Exception as exc:error=type(exc).__name__
        return name,None,error
    with ThreadPoolExecutor(max_workers=5) as pool:
        for name,value,error in pool.map(get,series_map.items()):
            if value is not None:out["macro"][name]=value
            else:out["errors"][name]=error
    alternatives={"cpi_index":"CUSR0000SA0","unemployment_pct":"LNS14000000","payrolls_thousands":"CES0000000001","ppi_index":"WPU00000000","effective_fed_funds_pct":"EFFR"}
    def fallback(item):
        name,series=item
        if name in out["macro"]:return name,None,None
        try:
            if series=="EFFR":
                value=effr(json.loads(fetch("https://markets.newyorkfed.org/api/rates/unsecured/effr/last/10.json")),now)
            else:
                value=bls(json.loads(fetch("https://api.bls.gov/publicAPI/v1/timeseries/data/"+series)),series,now)
            return name,value,None
        except Exception as exc:return name,None,type(exc).__name__
    with ThreadPoolExecutor(max_workers=5) as pool:
        for name,value,error in pool.map(fallback,alternatives.items()):
            if value is not None:
                out["macro"][name]=value
                out["errors"].pop(name,None)
            elif error:out["errors"][name+"_fallback"]=error
    out["macro_status"]="observations_only_no_release_calendar_or_consensus"
    DATA.mkdir(exist_ok=True);p=DATA/"BTC-market-breadth-macro-v1.json";t=p.with_suffix(".tmp");t.write_text(json.dumps(out,indent=2)+"\n");t.replace(p)
    print("Breadth and macro availability",bool(out["breadth"]),list(out["macro"]),out["errors"])
if __name__=="__main__":main()
