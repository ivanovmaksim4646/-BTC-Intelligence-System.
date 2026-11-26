# OKX Order Flow: stage 1 — REST coverage diagnostics and OI history

This stage does **not** claim complete Futures Delta/CVD. The existing `src/okx_futures_orderflow_v1.py` obtains **one capped REST page of 500 trades**, often spanning less than a minute. Even though it provides an accurate signed-BTC sum for the returned page after OKX `ctVal` verification, this does not establish M5/M15/H1/H4 trade completeness.

The new `src/okx_flow_coverage_v1.py` runs each normal BTC Intelligence Sync:
- Persists validated, timestamp-ordered OKX BTC-USDT-SWAP Open Interest snapshots in bounded `data/BTC-okx-oi-observations-v1.jsonl`.
- Reports an actual OI change only when two distinct verified OKX exchange timestamps are at most 20 minutes apart. This change is **not** a continuous intraperiod OI feed.
- Writes `data/BTC-okx-flow-coverage-v1.json` with sampled REST page duration, signed page BTC, explicit coverage status for M5/M15/H1/H4, nullable complete Delta and CVD fields.
- Rejects corrupt/conflicting history, out-of-order OI, stale snapshots and mixed venues. Repeated OI timestamps are not counted as new samples.
- Adds fresh, evidence-backed OI delta availability to `data/BTC-source-budget-v1.json`.

**Complete M5 Delta = null, continuous CVD = null** until a long-lived OKX public trades WebSocket collector is operating with persisted dedupe, reconnection, exact exchange timestamp bucket boundaries, replay/watermarks and auditable gap detection. A GitHub Actions REST run every 5 minutes or an earlier 35-second canary cannot establish this.

## Next implementation stage: continuous WebSocket

Use a separate, cost-reviewed Cloudflare Durable Object/WebSocket ingest from the existing scheduler. Require verified OKX contract multiplier, durable tradeId dedupe, exchange clock timestamps, sequential 5-minute boundary finalization, interrupt/reconnect detection and explicit completeness certificates. Reject incomplete buckets instead of inventing Delta/CVD. Aggregate only complete 5m buckets into 15m/H1/H4. Do not connect this data to a trading decision until bucket integrity and real-time reception are independently tested.

No new Cloudflare Worker is deployed by this first stage and no exchange orders are submitted.
