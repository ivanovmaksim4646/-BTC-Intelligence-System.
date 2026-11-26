#!/usr/bin/env python3
"""OKX public REST BTC-USDT-SWAP orderbook, funding and mark/index snapshot.

Observed REST book = resting, cancellable orders, NOT liquidation heatmap.
Funding is a current quoted rate; mark-index divergence is a snapshot,
not a dated futures cash-and-carry expiry basis. No orders or CVD claims.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

VENUE="OKX BTC-USDT-SWAP"
INST="BTC-USDT-SWAP"
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"BTC-okx-liquidity-derivatives-v1.json"
BASE="https://www.okx.com"

def positive(value):
    try:
        v=float(value)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError,TypeError,OverflowError):return None

def number(value):
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError,OverflowError):return None

def fetch(path,params,opener=urlopen):
    url=BASE+path+"?"+urlencode(params)
    with opener(Request(url,headers={"User-Agent":"BTC-Intelligence-OKX-Research/1.0",
                  "Accept":"application/json"}),timeout=15) as response:
        payload=json.load(response)
    if not isinstance(payload,dict) or str(payload.get("code"))!="0" or not isinstance(payload.get("data"),list):
        raise ValueError("unverified_okx_rest_response")
    return payload["data"]

def timestamp(value,now):
    try:
        ms=int(value)
        if not 0<=now.timestamp()*1000-ms<=180000:
            return None
        return ms
    except (TypeError,ValueError,OverflowError):return None

def single(rows,now,required_symbol=True):
    if not isinstance(rows,list) or len(rows)!=1 or not isinstance(rows[0],dict):
        return None
    row=rows[0]
    if required_symbol and row.get("instId")!=INST:return None
    return row

def evaluate(book, funding, mark, index, instruments, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone_required")
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":VENUE,"classification":"public_rest_snapshot_research_only",
       "book":{"status":"unavailable"},"funding":{"status":"unavailable"},
       "mark_index":{"status":"unavailable"},"trade_signal":None,
       "entry_signal":False,"complete_cvd_btc":None,"liquidation_heatmap":None,
       "warnings":[]}
    multiplier=None
    meta=single(instruments,now)
    if meta and meta.get("ctValCcy")=="BTC":
        multiplier=positive(meta.get("ctVal"))
    if multiplier is None:
        result["warnings"].append("instrument_ctval_btc_unverified")
    ob=single(book,now,False)
    if ob is not None and multiplier is not None:
        ts=timestamp(ob.get("ts"),now)
        bids,asks=ob.get("bids"),ob.get("asks")
        try:
            if ts is None or not isinstance(bids,list) or not isinstance(asks,list) or not bids or not asks:
                raise ValueError("book_missing_or_stale")
            if len(bids)>50 or len(asks)>50:raise ValueError("book_depth_unexpected")
            def parse_levels(rows,side):
                levels=[]
                for row in rows:
                    if not isinstance(row,list) or len(row)<2:
                        raise ValueError("invalid_book_row")
                    price=positive(row[0]);sz=positive(row[1])
                    if price is None or sz is None:raise ValueError("invalid_book_level")
                    levels.append({"price":price,"contracts":sz,"btc":round(sz*multiplier,8),
                                   "notional_usdt":round(price*sz*multiplier,2)})
                prices=[x["price"] for x in levels]
                if len(set(prices))!=len(prices) or any(
                    prices[i]>=prices[i-1] if side=="bid" else prices[i]<=prices[i-1]
                    for i in range(1,len(prices))):
                    raise ValueError("misordered_book")
                return levels
            bid=parse_levels(bids,"bid");ask=parse_levels(asks,"ask")
            if bid[0]["price"]>=ask[0]["price"]:
                raise ValueError("crossed_book")
            bid_btc=sum(x["btc"] for x in bid)
            ask_btc=sum(x["btc"] for x in ask)
            result["book"]={"status":"snapshot_only","timestamp_ms":ts,
                "best_bid":bid[0]["price"],"best_ask":ask[0]["price"],
                "spread_bps":round(10000*(ask[0]["price"]-bid[0]["price"])/((ask[0]["price"]+bid[0]["price"])/2),5),
                "bid_depth_btc":round(bid_btc,8),"ask_depth_btc":round(ask_btc,8),
                "resting_imbalance":round((bid_btc-ask_btc)/(bid_btc+ask_btc),6),
                "bid_walls":sorted(bid,key=lambda x:x["btc"],reverse=True)[:3],
                "ask_walls":sorted(ask,key=lambda x:x["btc"],reverse=True)[:3],
                "depth_levels":{"bid":len(bid),"ask":len(ask)},
                "limitations":["resting_orders_can_cancel_or_spoof",
                    "top_of_book_only_not_entire_market","not_liquidation_heatmap"]}
        except (ValueError,TypeError,ZeroDivisionError) as exc:
            result["warnings"].append(str(exc))
    elif ob is None:result["warnings"].append("book_unavailable")
    fr=single(funding,now)
    if fr is not None:
        rate=number(fr.get("fundingRate"))
        next_ts=fr.get("nextFundingTime")
        try:next_ms=int(next_ts)
        except (TypeError,ValueError):next_ms=0
        # The funding rate is a current snapshot, not paid historical funding.
        if rate is not None and abs(rate)<=0.05 and 0<next_ms-now.timestamp()*1000<48*3600*1000:
            result["funding"]={"status":"quoted_rate_snapshot",
               "rate_fraction":rate,"rate_percent":round(rate*100,7),
               "next_funding_time_ms":next_ms,"not_realized_funding":True}
        else:result["warnings"].append("funding_rate_invalid_or_next_time_unverified")
    else:result["warnings"].append("funding_unavailable")
    mr=single(mark,now)
    ix=single(index,now,False)
    if mr and ix and ix.get("instId")=="BTC-USDT":
        mt=timestamp(mr.get("ts"),now)
        it=timestamp(ix.get("ts"),now)
        mp=positive(mr.get("markPx"))
        ip=positive(ix.get("idxPx"))
        if mt is not None and it is not None and abs(mt-it)<=120000 and mp and ip:
            result["mark_index"]={"status":"two_recent_public_snapshots",
                "mark_price":mp,"index_price":ip,
                "mark_timestamp_ms":mt,"index_timestamp_ms":it,
                "mark_minus_index_usdt":round(mp-ip,4),
                "premium_bps":round(10000*(mp-ip)/ip,6),
                "warning":"instantaneous_mark_index_premium_not_calendar_futures_basis"}
        else:result["warnings"].append("stale_or_invalid_mark_index")
    else:result["warnings"].append("mark_or_index_unavailable")
    result["status"]="observed_partial" if (
        result["book"].get("status")=="snapshot_only" or
        result["funding"].get("status")=="quoted_rate_snapshot" or
        result["mark_index"].get("status")=="two_recent_public_snapshots") else "unavailable"
    return result

def collect(getter=fetch,now=None):
    requests={
      "book":("/api/v5/market/books",{"instId":INST,"sz":"50"}),
      "funding":("/api/v5/public/funding-rate",{"instId":INST}),
      "mark":("/api/v5/public/mark-price",{"instType":"SWAP","instId":INST}),
      "index":("/api/v5/market/index-tickers",{"instId":"BTC-USDT"}),
      "instruments":("/api/v5/public/instruments",{"instType":"SWAP","instId":INST}),
    }
    data={};errors={}
    for key,(path,params) in requests.items():
        try:data[key]=getter(path,params)
        except (OSError,ValueError,TypeError,TimeoutError) as exc:
            data[key]=[]
            errors[key]=type(exc).__name__
    report=evaluate(**data,now=now or dt.datetime.now(dt.timezone.utc))
    report["endpoint_errors"]=errors
    return report

def main():
    report=collect()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    tmp=OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(OUT)
    print("OKX depth/funding/mark-index",report["status"],
          "book",report["book"]["status"],"funding",report["funding"]["status"],
          "mark-index",report["mark_index"]["status"],report["warnings"])
if __name__=="__main__":main()
