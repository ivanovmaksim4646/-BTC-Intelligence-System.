#!/usr/bin/env python3
"""Read-only BTC market data source budget guard.

Never retire a source on the strength of a REST page, a 35-second websocket
canary, or an unverified status label. Gate OKX migration on independent
features. This module DOES NOT switch off data sources or place trades.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"
OUTPUT=DATA/"BTC-source-budget-v1.json"
SOURCE="OKX BTC-USDT-SWAP"
TIMES=("5m","15m","1h","4h","1d","1w")

def recent_iso(value,now,minutes=15):
    try:
        date=datetime.fromisoformat(value.replace("Z","+00:00"))
        return date.tzinfo is not None and timedelta(0)<=now-date<=timedelta(minutes=minutes)
    except (ValueError,TypeError,AttributeError):
        return False

def evaluate(okx, bingx, now=None, okx_candles=None, okx_ict=None):
    now=now or datetime.now(timezone.utc)
    okx=okx if isinstance(okx,dict) else {}
    bingx=bingx if isinstance(bingx,dict) else {}
    okx_candles=okx_candles if isinstance(okx_candles,dict) else {}
    okx_ict=okx_ict if isinstance(okx_ict,dict) else {}
    o=okx.get("open_interest") if isinstance(okx.get("open_interest"),dict) else {}
    c=okx.get("candles") if isinstance(okx.get("candles"),dict) else {}
    tr=okx.get("recent_trades") if isinstance(okx.get("recent_trades"),dict) else {}
    frames=bingx.get("timeframes") if isinstance(bingx.get("timeframes"),dict) else {}
    okx_fresh=okx.get("source")==SOURCE and recent_iso(okx.get("collected_at_utc"),now)
    bingx_fresh=bingx.get("source")=="BingX USD-M Perpetual BTC-USDT" and recent_iso(bingx.get("collected_at_utc"),now)
    okx_candle_frames=okx_candles.get("timeframes") if isinstance(okx_candles.get("timeframes"),dict) else {}
    okx_candle_verified=(okx_candles.get("source")==SOURCE and
        okx_candles.get("status")=="verified" and
        recent_iso(okx_candles.get("collected_at_utc"),now) and
        all(isinstance(okx_candle_frames.get(tf),dict) and
            okx_candle_frames[tf].get("status")=="ok" and
            len(okx_candle_frames[tf].get("bars") or [])>=30
            for tf in TIMES))
    okx_ict_research=(okx_candle_verified and okx_ict.get("source")==SOURCE
        and okx_ict.get("classification")=="futures_research_only"
        and okx_ict.get("decision")=="NO_TRADE"
        and recent_iso(okx_ict.get("evaluated_at_utc"),now)
        and isinstance(okx_ict.get("ifvg"),dict))
    okx_features={
        "live_rest_trade_page":okx_fresh and tr.get("status")=="observed",
        "closed_m5_candles":okx_fresh and c.get("status")=="observed",
        "oi_snapshot":okx_fresh and o.get("status")=="snapshot_only",
        "complete_m5_delta":False,
        "continuous_cvd_5m_15m_1h_4h":False,
        "closed_candles_5m_15m_1h_4h_1d_1w":okx_candle_verified,
        "okx_ict_observations_available":okx_ict_research,
        "validated_okx_poi_qm_ifvg":False,
        "risk_engine_venue_migrated":False,
        "tradingview_venue_aligned":False,
    }
    # Deliberately do not infer complete windows from "observed" data.
    # This gate must be explicitly updated with separately tested provenance
    # and end-to-end validations when the missing modules actually exist.
    bingx_features={t:(bingx_fresh and isinstance(frames.get(t),dict) and
                        frames[t].get("status")=="ok") for t in TIMES}
    required=("closed_candles_5m_15m_1h_4h_1d_1w",
              "validated_okx_poi_qm_ifvg","risk_engine_venue_migrated",
              "tradingview_venue_aligned")
    return {
        "schema_version":"1.0",
        "evaluated_at_utc":now.isoformat(),
        "decision":"RETAIN_BINGX",
        "switch_approved":False,
        "classification":"data_cost_and_venue_migration_audit_only",
        "primary_venue_target":SOURCE,
        "okx_features":okx_features,
        "bingx_features":bingx_features,
        "reasons":["OKX REST trade page is not complete Delta/CVD",
                   "OKX M5-W1 candles and ICT research are being verified; model is not validated for trading",
                   "Risk Engine v1 and TradingView still reference BingX",
                   "Kraken provides independent Spot/Futures confirmation",
                   "Removing BingX saves GitHub API calls, not persistent Cloudflare DO duration"],
        "safe_immediate_savings":[
            "remove_redundant_5_minute_cron_from_already_completed_okx_canary",
            "do_not_run_extra_okx_history_pagination_30_pages_every_sync",
            "retain_existing_bingx_and_kraken_until_venue_migration_is_tested"
        ],
        "trade_signal":None,
    }

def main():
    def read(name):
        try:return json.loads((DATA/name).read_text(encoding="utf-8"))
        except (OSError,ValueError):return {}
    output=evaluate(read("BTC-okx-orderflow-v1.json"),read("BTC-bingx-futures-probe.json"),
                    okx_candles=read("BTC-okx-futures-candles.json"),okx_ict=read("BTC-okx-poi-qm-v1.json"))
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(output,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("SOURCE BUDGET GUARD:",output["decision"],"OKX verified REST trade page",
          output["okx_features"]["live_rest_trade_page"])

if __name__=="__main__":
    main()
