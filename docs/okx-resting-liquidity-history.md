# OKX resting liquidity history (free REST sampling)

The BTC Intelligence Sync independently collects a public OKX BTC-USDT-SWAP top-50 order book, quoted funding, mark/index premium, and existing timestamped Open Interest observations.

This module runs **after** the REST snapshot collector on every successful/partial BTC sync and records:

- `data/BTC-okx-liquidity-history-v1.jsonl`: up to 2,500 deduplicated, time-ordered observations with bid/ask depth in BTC, best bid/ask, top-3 resting walls per side, optional quoted funding and instantaneous mark/index premium.
- `data/BTC-okx-liquidity-history-analysis-v1.json`: number of saved observations, current record and two-point changes for bid/ask BTC depth, imbalance, quoted funding and mark/index premium when samples are at most 20 minutes apart.
- Existing `data/BTC-okx-oi-observations-v1.jsonl` and `data/BTC-okx-flow-coverage-v1.json` independently track OKX Open Interest level and verified two-snapshot change.

Only the originally observed REST snapshots may enter this history. Invalid or stale timestamps, mixed venues, crossed/missing books, duplicate exchange book timestamps and corrupt pre-existing history are rejected. The journal is bounded to limit repository data growth. This uses only pre-existing GitHub Actions + free public OKX endpoints, with no paid Cloudflare WebSocket deployment.

**Interpretation constraints:**

1. Changes in displayed resting Bid/Ask volume reflect two discrete depth snapshots, not executed buy/sell Delta, individual cancellations, spoofing certainty, or liquidation heatmaps.
2. A 5-minute GitHub schedule does **not** make this a gap-free live order-book event stream. Missing/late snapshots remain gaps.
3. Funding is quoted, not a realized payment. Mark/index premium is not cash-and-carry expiry basis.
4. Delta/CVD and any trading signal remain `null`. These data can supplement narrative market context but cannot independently justify execution.
5. The historical snapshots are not replay/backtest-ready execution fills. No account keys are used.

Next: classify repeated wall persistence/relocation across **sufficient** consecutive snapshots with explicit missing-data and market-move caveats, without interpreting it as confirmed absorption.
