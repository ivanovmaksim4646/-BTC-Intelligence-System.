# OKX WebSocket Delta/CVD — bounded pilot, NOT deployed

## Evidence and economics checked 2026-11-26

- OKX public `trades` on `/ws/v5/public` **aggregates multiple trades** into a single message; its `count` field represents aggregated fills. Full individual fill research should instead test `trades-all` at `wss://ws.okx.com/ws/v5/business` (public subscription, one trade per message), for `BTC-USDT-SWAP`. Official OKX API reference: https://www.okx.com/docs-v5/en/
- A Cloudflare Durable Object with an **outbound** WebSocket incurs billable duration while the connection holds it awake; hibernation is for inbound client WebSockets. Official reference: https://developers.cloudflare.com/durable-objects/platform/pricing/ and https://developers.cloudflare.com/durable-objects/best-practices/websockets/
- GitHub CI read-only Cloudflare `GET /accounts/{account}/subscriptions` returned HTTP **403**. Existing deployment token cannot certify the paid/free plan or spending limit. Never infer that costs are zero.
- Consequently, **NO continuous streaming Worker is auto-deployed or scheduled**. The pre-existing 35-second canary and production scheduler remain unchanged.

## Prepared and unit-tested (no deployment)

- `cloudflare/okx-flow-bucket-engine.mjs`: strict dedupe by raw trade ID, verify OKX symbol, size and contract multiplier, use EXCHANGE timestamp to bucket buy/sell BTC signed observations into M5; flag reconnect interruptions, clock anomalies and memory overflow. The response exposes **observed** Delta, NOT gap-certified complete Delta or CVD.
- `cloudflare/okx-flow-pilot.mjs`: 7-minute maximum one-use, opt-in and token-gated `trades-all` research pilot with no orders; active outbound socket is force-closed on alarm and on error. Production scheduler is never modified.
- `cloudflare/wrangler-okx-flow-pilot.jsonc`: distinct SQLite Durable Object class; `FLOW_PILOT_ENABLED=false`, no cron and no auto-deploy workflow. The config must not be used by production.
- `cloudflare/okx-flow-bucket-engine.test.mjs` and `cloudflare/okx-flow-pilot.test.mjs` exercise trade accounting, candle alignment, duplicate IDs, interruptions, bounded lifecycle and safe off-by-default behavior.

## Required before any pilot deployment

1. Confirm Cloudflare Workers plan and billable-Durable-Object duration for the account; enable an actual monetary spending limit or acceptable hard cap.
2. Review worker separation, private control token and explicit opt-in `FLOW_PILOT_ENABLED=true`. No keys in repository or TradingView webhook.
3. Run **only the bounded pilot**, inspect real OKX `trades-all` schema, verified contract units, message volume and durable-memory pressure. Verify the 7-minute alarm closes it.
4. Before claiming full M5/H4 CVD, engineer replay/provenance or independent exchange sequence/gap checks. A socket that stays connected for 5 minutes does **not** by itself prove delivery of every exchange trade. If this cannot be certified, report observed Delta with clear caveats and keep complete Delta/CVD null.
5. Connect only independently validated flow confidence into entry evidence. No live trading until model validation.

**Do not turn on the pilot or a 24/7 outgoing WebSocket merely because the CI tests pass.**
