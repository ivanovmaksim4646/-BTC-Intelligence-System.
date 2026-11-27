"""Strict volume reconciliation and gap-aware rolling flow windows.
Volume reconciliation is evidence, not proof of exchange-level completeness.
No order execution or production writes.
"""
from decimal import Decimal
M5=300000
INSTRUMENTS=("BTC-USDT","BTC-USDT-SWAP")
def decimal(value):
    v=Decimal(str(value))
    if not v.is_finite():raise ValueError("nonfinite quantity")
    return v

def reconcile(report,candles,metadata=()):
    r=dict(report)
    r.update(volume_reconciled=False,delta_btc_reconciled=None,volume_btc_reconciled=None)
    inst=r.get("instrument")
    if inst not in INSTRUMENTS or not r.get("both_time_boundaries_observed"):
        r["reconciliation_reason"]="incomplete_boundaries";return r
    start=r["start_ms"]
    if type(start) is not int or start%M5 or r["end_ms"]!=start+M5:
        raise ValueError("invalid bucket boundary")
    rows=[x for x in candles if len(x)>=9 and int(x[0])==start and str(x[8])=="1"]
    if len(rows)!=1:
        r["reconciliation_reason"]="closed_candle_unavailable";return r
    buy=decimal(r["observed_buy_native"]);sell=decimal(r["observed_sell_native"])
    vol=decimal(rows[0][5])
    if min(buy,sell,vol)<0:raise ValueError("negative volume")
    r["candle_volume_native"]=str(vol)
    r["observed_volume_native"]=str(buy+sell)
    r["volume_difference_native"]=str(buy+sell-vol)
    if buy+sell!=vol:
        r["reconciliation_reason"]="volume_mismatch";return r
    multiplier=Decimal(1)
    if inst=="BTC-USDT-SWAP":
        matches=[m for m in metadata if m.get("instId")==inst and m.get("ctValCcy")=="BTC" and m.get("ctType")=="linear"]
        if len(matches)!=1:
            r["reconciliation_reason"]="contract_metadata_unavailable";return r
        multiplier=decimal(matches[0]["ctVal"])
        if multiplier<=0:raise ValueError("invalid multiplier")
    quote = decimal(rows[0][7])
    r.update(open_usdt=str(decimal(rows[0][1])), close_usdt=str(decimal(rows[0][4])),
             quote_volume_usdt=str(quote) if quote > 0 or vol == 0 else None)
    r.update(volume_reconciled=True,reconciliation_reason="exact_native_candle_volume_match",
             delta_btc_reconciled=str((buy-sell)*multiplier),
             volume_btc_reconciled=str(vol*multiplier))
    return r

def aggregate(rows,end,inst):
    if inst not in INSTRUMENTS or type(end) is not int or end%M5:
        raise ValueError("invalid instrument or end")
    indexed={}
    for r in rows:
        if r.get("instrument")!=inst:continue
        t=r.get("end_ms")
        if type(t) is not int or t%M5 or r.get("start_ms")!=t-M5:
            raise ValueError("invalid bucket")
        if t in indexed and indexed[t]!=r:raise ValueError("conflicting duplicate bucket")
        indexed[t]=r
    result={}
    for label,n in (("5m",1),("15m",3),("1h",12),("4h",48)):
        expected=range(end-(n-1)*M5,end+1,M5)
        verified=[indexed[t] for t in expected if t in indexed and indexed[t].get("volume_reconciled") is True]
        valid=len(verified)==n
        result[label]={"required_m5":n,"reconciled_m5":len(verified),"start_ms":end-n*M5,"end_ms":end,
          "delta_btc_reconciled":str(sum((decimal(r["delta_btc_reconciled"]) for r in verified),Decimal(0))) if valid else None,
          "volume_btc_reconciled":str(sum((decimal(r["volume_btc_reconciled"]) for r in verified),Decimal(0))) if valid else None,
          "cvd_change_btc_reconciled":str(sum((decimal(r["delta_btc_reconciled"]) for r in verified),Decimal(0))) if valid else None,
          "complete_delta_btc":None,"complete_cvd_btc":None,
          "coverage":"volume_reconciled_not_sequence_certified" if valid else "missing_or_unreconciled_m5"}
        w = result[label]
        w["buy_volume_btc"] = w["sell_volume_btc"] = None
        w["price_delta_divergence_candidate"] = None
        if valid:
            v = decimal(w["volume_btc_reconciled"])
            delta = decimal(w["delta_btc_reconciled"])
            w["buy_volume_btc"] = str((v + delta) / 2)
            w["sell_volume_btc"] = str((v - delta) / 2)
            first, last = verified[0], verified[-1]
            if first.get("open_usdt") and last.get("close_usdt"):
                change = decimal(last["close_usdt"]) - decimal(first["open_usdt"])
                w["price_delta_divergence_candidate"] = change * delta < 0
    return result
