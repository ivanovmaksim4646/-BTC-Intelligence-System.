#!/usr/bin/env python3
"""BingX-specific futures POI -> QM observations. Read-only research."""
import json
from pathlib import Path
try:
    from src.binance_poi_qm_v1 import evaluate
except ModuleNotFoundError:
    from binance_poi_qm_v1 import evaluate

DATA=Path(__file__).resolve().parents[1]/"data"
VENUE="BingX USD-M Perpetual BTC-USDT"

def main():
    try:
        snap=json.loads((DATA/"BTC-bingx-futures-probe.json").read_text(encoding="utf-8"))
    except (OSError,ValueError):
        snap={}
    out=evaluate(snap,expected_source=VENUE)
    out["chart_relation"]="Same BingX BTC-USDT perpetual venue as TradingView BINGX:BTCUSDT.P; events still require separate timestamp matching."
    out["entry_signal"]=False
    dest=DATA/"BTC-bingx-poi-qm-v1.json"
    temp=dest.with_suffix(".json.tmp")
    temp.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(dest)
    print("BingX futures POI/QM:",len(out["observations"]),"observations; NO_TRADE")

if __name__=="__main__":
    main()
