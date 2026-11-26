#!/usr/bin/env python3
"""Read-only RR outcome statistics: never manufactures historical trades.

Only explicitly supplied, independently validated OKX closed-candle
counterfactual outcomes are eligible. Without those records, publish null
win rate/expectancy/profit factor rather than a false result.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import json
try:
    from src.rr_outcome_research_v1 import aggregate,TARGET_R
except ModuleNotFoundError:
    from rr_outcome_research_v1 import aggregate,TARGET_R

DATA=Path(__file__).resolve().parents[1]/"data"
JOURNAL=DATA/"BTC-rr-validated-outcomes-v1.jsonl"
REPORT=DATA/"BTC-rr-statistics-v1.json"
VENUE="OKX BTC-USDT-SWAP"

def build(records,now=None):
    now=now or datetime.now(timezone.utc)
    eligible=[];seen=set();errors=[]
    for index,row in enumerate(records):
        if not isinstance(row,dict):
            errors.append(index);continue
        ident=row.get("entry_id")
        # No source provenance, lookahead-safe validation or proof = not eligible.
        if (row.get("source")!=VENUE or row.get("classification")!="validated_closed_candle_counterfactual"
            or row.get("entry_provenance_verified") is not True
            or row.get("future_bars_verified") is not True
            or not isinstance(ident,str) or not ident or ident in seen
            or not isinstance(row.get("outcomes"),dict)):
            errors.append(index);continue
        seen.add(ident)
        eligible.append(row)
    result={"schema_version":"1.0","generated_at_utc":now.isoformat(),
            "source":VENUE,"classification":"historical_rr_research_only",
            "entry_count":len(eligible),"rejected_records":len(errors),
            "trade_signal":None,"performance_verified":False,
            "minimum_data_rule":"No recommendation from small or unvalidated outcome samples",
            "note":"No real outcomes yet unless separately verified JSONL records exist; observed dataset, never simulated from assumed wins.",
            "by_rr":aggregate(eligible)}
    return result

def main():
    records=[]
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            if not line.strip():continue
            try:records.append(json.loads(line))
            except ValueError:records.append(None)
    out=build(records)
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    t=REPORT.with_suffix(".json.tmp")
    t.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(REPORT)
    print("RR research journal:",out["entry_count"],"eligible,",out["rejected_records"],"rejected. No live signals.")
if __name__=="__main__":main()
