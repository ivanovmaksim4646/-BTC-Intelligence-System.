#!/usr/bin/env python3
"""Compact snapshot-only OKX context for existing BTC reports; no trade advice."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
DATA=Path(__file__).resolve().parents[1]/"data"
OUT=DATA/"BTC-okx-derivatives-context-v1.json"
VENUE="OKX BTC-USDT-SWAP"

def fresh(ts,now,seconds=900):
    try:
        when=dt.datetime.fromisoformat(ts.replace("Z","+00:00"))
        return when.tzinfo is not None and 0<=(now-when).total_seconds()<=seconds
    except (TypeError,ValueError,AttributeError):return False

def build(liquidity,flow,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    liquidity=liquidity if isinstance(liquidity,dict) else {}
    flow=flow if isinstance(flow,dict) else {}
    valid=(liquidity.get("source")==VENUE and
           liquidity.get("classification")=="public_rest_snapshot_research_only"
           and fresh(liquidity.get("generated_at_utc"),now))
    flow_valid=(flow.get("source")==VENUE and
        flow.get("classification")=="partial_rest_flow_audit_only"
        and fresh(flow.get("generated_at_utc"),now))
    b=liquidity.get("book") if valid and isinstance(liquidity.get("book"),dict) else {}
    f=liquidity.get("funding") if valid and isinstance(liquidity.get("funding"),dict) else {}
    m=liquidity.get("mark_index") if valid and isinstance(liquidity.get("mark_index"),dict) else {}
    change=flow.get("oi_change") if flow_valid else None
    return {"schema_version":"1.0","generated_at_utc":now.isoformat(),
       "source":VENUE,"classification":"read_only_okx_snapshot_context",
       "book":b if b.get("status")=="snapshot_only" else None,
       "funding":f if f.get("status")=="quoted_rate_snapshot" else None,
       "mark_index":m if m.get("status")=="two_recent_public_snapshots" else None,
       "oi_change":change if isinstance(change,dict) and
                           change.get("status")=="two_verified_snapshots" else None,
       "full_delta_btc":None,"full_cvd_btc":None,
       "liquidation_heatmap":None,"trade_signal":None,
       "note":"Walls are cancellable resting orders. Funding is quoted. Mark-index is not dated futures basis. OI change is two discrete snapshots."}

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    result=build(read("BTC-okx-liquidity-derivatives-v1.json"),
                 read("BTC-okx-flow-coverage-v1.json"))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    t=OUT.with_suffix(".json.tmp")
    t.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(OUT)
    print("OKX derivatives report context",bool(result["book"]),bool(result["funding"]),
          bool(result["mark_index"]),bool(result["oi_change"]))
if __name__=="__main__":main()
