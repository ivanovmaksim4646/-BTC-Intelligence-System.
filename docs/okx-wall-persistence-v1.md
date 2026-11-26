# OKX sampled resting wall price-zone persistence v1

The free public REST history `data/BTC-okx-liquidity-history-v1.jsonl` contains discrete top-three visible resting Bid and Ask price levels extracted from the top-50 order book. The observational module `src/okx_wall_persistence_v1.py` executes **after** the snapshot history append in each regular GitHub Actions BTC Sync.

Output: `data/BTC-okx-wall-persistence-v1.json`.

A zone is reported as *persistently visible in sampled top-three walls* only when:
- At least three independent, chronological OKX exchange-timestamp snapshots exist.
- Each adjacent sample is no more than ten minutes apart; a broken sample sequence resets to the most recent contiguous suffix.
- The latest sample is no older than fifteen minutes at evaluation.
- Every compared midprice is no farther than fifty basis points from the latest midprice, avoiding comparisons across major market moves.
- A wall on the same book side matches within **0.5 basis points** in every successive snapshot, with strict one-to-one matching (a level cannot be reused for multiple chains).
- At most twelve consecutive snapshots are compared. The top-three rankings and volume may fluctuate; a zone is a *price region*, not individual order identity.

The report also lists price zones present in the **latest** top-three list but absent from the preceding sample (`newly_visible`) and vice versa (`no_longer_top3`). These are **not** reliable cancellation, addition, fill, absorption, or spoofing events. A missing zone can move beyond the top-three level selection without being cancelled.

**Provenance and safety:** Multiple snapshots do not establish intraperiod continuity. Resting orders can be added, cancelled, filled, or spoofed between observations. This system does not observe order identity, full market depth events, execution prints, liquidation heatmap, or complete CVD/Delta. All such claims and trade signals are null. No live orders, subscriptions, paid WebSockets, or exchange credentials are used.

When data are sparse, stale, gapped, price-regime-incompatible or malformed, the module fails closed to `insufficient_history`, `stale_history`, `noncomparable_price_regime` or `invalid_history`. Its status is not a forecast or signal.
