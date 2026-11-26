#!/usr/bin/env python3
"""OKX-only POI/FVG/IFVG + QM observational migration, NO TRADE."""
import json
from pathlib import Path
try:
    from src.binance_poi_qm_v1 import evaluate
except ModuleNotFoundError:
    from binance_poi_qm_v1 import evaluate

DATA=Path(__file__).resolve().parents[1]/"data"
VENUE="OKX BTC-USDT-SWAP"

def main():
    try:
        snap=json.loads((DATA/"BTC-okx-futures-candles.json").read_text(encoding="utf-8"))
    except (OSError,ValueError):
        snap={}
    result=evaluate(snap,expected_source=VENUE)
    result["chart_relation"]="All FVG/IFVG/QM research candles originate from OKX BTC-USDT-SWAP. TradingView venue still requires migration."
    result["entry_signal"]=False
    result["trade_signal"]=None
    result["venue_migration"]="research_ict_okx_only_risk_engine_and_tradingview_not_migrated"
    out=DATA/"BTC-okx-poi-qm-v1.json"
    tmp=out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(out)
    print("OKX POI IFVG QM:",len(result["observations"]),"observations, NO_TRADE",result["reasons"])

if __name__=="__main__":main()
