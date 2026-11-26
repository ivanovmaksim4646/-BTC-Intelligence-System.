#!/usr/bin/env python3
"""Cross-timeframe POI touch -> QM -> retest on SAME Binance BTCUSDT futures.

Conservative observational candidate, not an entry engine. Prevents use of
the currently forming candle and prevents treating an old touch as new.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
try:
    from src.strategy_models_v1 import scan_qm, scan_ifvg
except ModuleNotFoundError:
    from strategy_models_v1 import scan_qm, scan_ifvg

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
HTF={"1h":3600,"4h":14400,"1d":86400,"1w":604800}
LTF={"5m":300,"15m":900}

def fvg_zones(bars):
    zones=[]
    for i in range(2,len(bars)):
        a,c=bars[i-2],bars[i]
        if c["l"]>a["h"]:
            zones.append({"direction":"long","low":a["h"],"high":c["l"],"formed":c["t"]})
        elif c["h"]<a["l"]:
            zones.append({"direction":"short","low":c["h"],"high":a["l"],"formed":c["t"]})
    return zones[-30:]

def overlaps(b,lo,hi):
    return b["l"]<=hi and b["h"]>=lo

def evaluate(snapshot, now=None, expected_source="Binance USD-M Futures BTCUSDT PERPETUAL"):
    now=now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None:raise ValueError("timezone required")
    result={"schema_version":"1.0","classification":"futures_research_only",
            "evaluated_at_utc":now.isoformat(),"source":expected_source,
            "decision":"NO_TRADE","trade_signal":None,"entry":None,"sl":None,"tp":None,"rr":None,
            "observations":[],"ifvg":{},"reasons":[]}
    stamp=dt.datetime.fromisoformat(snapshot.get("collected_at_utc","1970-01-01T00:00:00+00:00").replace("Z","+00:00"))
    if (snapshot.get("source")!=result["source"] or snapshot.get("status")!="verified"
        or stamp.utcoffset() is None or not dt.timedelta(0)<=now-stamp<=dt.timedelta(minutes=15)):
        result["reasons"].append("missing_or_stale_verified_futures_candles")
        return result
    tfs=snapshot.get("timeframes") or {}
    bars={}
    for tf in list(HTF)+list(LTF):
        item=tfs.get(tf) or {}
        if item.get("status")!="ok" or len(item.get("bars") or [])<30:
            result["reasons"].append("missing_"+tf)
            return result
        bars[tf]=item["bars"]
    for tf in HTF:
        result["ifvg"][tf]=scan_ifvg(bars[tf])[-10:]
    # The same-venue POI must precede touch, QM pattern and shoulder retest.
    # Cap search to recent LTF history for bounded, reproducible processing.
    observations=[]
    for ltf,seconds in LTF.items():
        last=bars[ltf]
        qms=scan_qm(last)
        for q in qms:
            if q.get("direction") not in ("long","short"):continue
            head=q.get("head_time")
            extreme=q.get("structural_extreme_time")
            shoulder=q.get("left_shoulder")
            if not all(type(x) in (int,float) and math.isfinite(x) for x in (head,extreme,shoulder)):continue
            # Pivots are 2/2: wait for two additional CLOSED bars after the
            # 4th pivot before checking any later retest.
            ready=extreme+3*seconds
            retests=[b for b in last if b["t"]>=ready and b["t"]>head and
                     abs(b["c"]-shoulder)/shoulder<=0.001 and
                     b["l"]<=shoulder<=b["h"] and
                     ((b["c"]>shoulder) if q["direction"]=="long" else (b["c"]<shoulder))]
            if not retests:continue
            first_retest=retests[0]
            if now.timestamp()-(first_retest["t"]+seconds)>3600:continue
            for htf in HTF:
                for poi in fvg_zones(bars[htf]):
                    if poi["direction"]!=q["direction"]:continue
                    touches=[b for b in last if b["t"]>=poi["formed"]+HTF[htf]
                             and b["t"]<head and overlaps(b,poi["low"],poi["high"])]
                    if not touches:continue
                    # Touch and QM must have chronological order. Same-venue
                    # event is not an independently verified HTF OB.
                    observations.append({"htf":htf,"ltf":ltf,"direction":q["direction"],
                        "poi_type":"3_candle_fvg","poi_low":poi["low"],"poi_high":poi["high"],
                        "poi_formed_at":poi["formed"],"touch_at":touches[-1]["t"],
                        "qm_head_at":head,"qm_extreme_at":extreme,
                        "qm_shoulder":shoulder,"qm_retest_at":first_retest["t"],
                        "status":"historical_sequence_observed",
                        "entry_signal":False})
    observations.sort(key=lambda x:x["qm_retest_at"],reverse=True)
    result["observations"]=observations[:20]
    result["reasons"].extend([
        "historical_pattern_not_live_entry",
        "execution_price_sl_tp_and_liquidity_not_verified",
        "requires_forward_and_backtesting"])
    return result

def main():
    try:
        snap=json.loads((DATA/"BTC-binance-futures-candles.json").read_text(encoding="utf-8"))
    except (OSError,ValueError):
        snap={}
    out=evaluate(snap)
    p=DATA/"BTC-binance-poi-qm-v1.json"
    t=p.with_suffix(".json.tmp")
    t.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    t.replace(p)
    print("Binance POI/QM:",len(out["observations"]),"historical observations, NO_TRADE")

if __name__=="__main__":
    main()
