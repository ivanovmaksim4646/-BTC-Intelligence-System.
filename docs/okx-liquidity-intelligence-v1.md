# OKX Liquidity Intelligence v1 — read-only research

Every BTC Intelligence Sync after the OKX public REST collectors and historical journal generation evaluates `src/okx_liquidity_intelligence_v1.py`, saving `data/BTC-okx-liquidity-intelligence-v1.json`.

Inputs (each **must** match the exact OKX BTC-USDT-SWAP source identifier, expected classification and age <=15m):
- `BTC-okx-derivatives-context-v1.json`: fresh resting book, quoted funding, mark/index premium.
- `BTC-okx-liquidity-history-analysis-v1.json`: exchange-book-timestamp-aligned bid/ask depth changes from TWO samples separated by <=20m; no continuous interval coverage.
- `BTC-okx-wall-persistence-v1.json`: <=12 most recent valid, gap-checked, sampled top-three price-zone repetitions; at least three observations, but **not** verified uninterrupted individual order identity.
- `BTC-okx-flow-coverage-v1.json`: OKX Open Interest level and authenticated two-snapshot change (<=20m), aligned within two minutes of the book timestamp. No complete intraperiod OI.

The aggregation checks source, freshness, book exchange timestamps, market-data synchronization within two minutes, finite data, expected snapshot statuses, gap/coverage limitations, and signs of contradictory or unavailable measurements. It exposes separate observational fields and context tags, with explicit null values for unobserved metrics.

`multi_source_observational_context` means four or more **available observational fields**, **not independent signal confirmations**, statistical significance, prediction confidence, or a trading opportunity. The same venue/market movement can influence all fields. A displayed positive bid imbalance is a resting snapshot, not executed buy volume. Likewise, OI change cannot alone classify whether new shorts or longs were opened.

No liquidation heatmap, confirmed spoofing, confirmed absorption, complete Delta/CVD, execution, long/short score, percentage forecast, SL/TP or trade alert is created. Every evaluation forces `decision=NO_TRADE`, `trade_signal=null` and `execution_ready=false`. Missing/stale/misaligned data are omitted, not synthesized.

This is free public OKX REST + existing scheduled GitHub Actions only. No account keys, paid WebSockets, subscriptions, exchange orders, or Cloudflare plan changes.
