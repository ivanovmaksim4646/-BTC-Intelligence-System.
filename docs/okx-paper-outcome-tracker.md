# OKX Paper Entry Journal & Outcome Tracker v1

The system deliberately separates three layers:

1. **TradingView alert** → `data/BTC-tradingview-events.jsonl`: market observations. Never transactions.
2. **OKX corroborated observation** → `data/BTC-okx-setup-observations-v1.jsonl`: same-venue, closed-candle ICT events. Never claimed entries.
3. **Independently validated paper entry** → `data/BTC-okx-validated-paper-entries-v1.jsonl`: **not created by current modules**. Future deterministic validator must prove POI → QM retest → opposing liquidity target, entry timing, and real same-venue evidence. Only these entries are eligible for outcome tracking.

### Automatically running now

Each BTC Intelligence Sync collects fresh OKX confirmed 5-minute bars, appends/reconciles history to `data/BTC-okx-m5-closed-history-v1.jsonl`, and runs `src/okx_outcome_tracker_v1.py`.

- Tracks each validated paper entry using only **future CLOSED** OKX M5 OHLC candles.
- For levels 1R/1.5R/2R/2.5R/3R/4R/5R, determines whether TP or SL was touched first; same-candle order is **ambiguous**.
- Does not interpolate missing 5-minute candles, merge venues, infer execution prices, or invent sample statistics.
- Fully resolved paper entry outcomes are appended once to `data/BTC-rr-validated-outcomes-v1.jsonl`. Historical existing records are never overwritten.
- Produces `data/BTC-okx-outcome-tracker-v1.json` audit and refreshes `data/BTC-rr-statistics-v1.json` after outcomes.
- The collector retains up to 10,000 M5 bars (~34 days); older entries are censored as history unavailable.
- The output is **paper-only** (no actual executed trades, no live trading, no account connection). Fees/slippage are estimates. OHLC touch at quoted levels is not fill evidence.
- **No confirmed paper entries yet** means 0 finalized results and null Win Rate/Expectancy, not failure.

### Validated entry contract

For future integration, entry records must include `entry_id`, `source:"OKX BTC-USDT-SWAP"`, `classification:"validated_paper_entry_only"`, `execution:"not_executed"`, `entry_signal:false`, `trade_signal:null`, `independent_entry_validator:"okx_poi_qm_execution_validator_v1"`, `venue_candle_close_verified:true`, `independent_target_verified:true`, `direction`, `entry`, `stop_loss`, `take_profit`, `entry_close_utc` (integer seconds, 5-minute aligned), `risk_fraction` (<=1%), `leverage_cap` (<=5), and nonnegative `total_cost_bps` (round-trip estimated).

**IMPORTANT:** record flags alone are not proof; a future entry validator must generate entries from traceable closed-candle and level evidence. Do not manually fabricate entry rows just to populate statistics.

### Next milestone

Build the deterministic independently sourced **OKX POI/QM retest and liquidity-target entry validator**, and confirm actual OKX TradingView venue before producing any paper entries for this tracker.
