# OKX Market Context v1 — confirmed swing structure + sampled liquidity

Every BTC Intelligence Sync runs `src/okx_market_context_v1.py` **after** collecting closed OKX M5/M15/H1/H4 candles and `BTC-okx-liquidity-intelligence-v1.json`. Output: `data/BTC-okx-market-context-v1.json`.

## What is actually measured

- All OHLC bars must be closed, contiguous, correctly timestamp-aligned OKX BTC-USDT-SWAP futures. Current closed-candle status and source age are checked for every timeframe.
- A swing high/low requires two closed bars on each side. The two most recent confirmed swing-highs and swing-lows determine a **descriptive** HH/HL (`bullish`) or LH/LL (`bearish`) structure per timeframe; otherwise the frame is `mixed` or `insufficient_pivots`. This is not a rigorously defined break-of-structure or character shift.
- H1 and H4 must agree for higher-timeframe (`htf_structure`) classification; M5 and M15 for lower-timeframe (`ltf_structure`). Overall market classification is directional only when both groups agree. Other arrangements remain `mixed`.
- Only recent and same-venue, exchange-time-aligned liquidity observations can be attached. A resting Bid/Ask imbalance, sampled depth change, OI delta, quoted funding, mark/index premium or price-zone presence is *context*, never an independent entry confirmation. Descriptive disagreements between LTF swing state and resting-book weight are tagged as **observational** only.
- Independently produced historical IFVG observations may be included as historical zones if they predate the latest closed M5 bar, never as live entry confirmation.

## Boundaries

`NO_TRADE` is enforced on every evaluation. No order placement, signals, percentages/probabilities, execution price, stop, target, validated POI/QM retest, full Delta/CVD, absorption or liquidation heatmap is inferred. Mixed price structure can be a valid market assessment rather than a missing-data error. Missing, stale, cross-venue, malformed or gapped sources fail closed.

The module is built entirely on existing free public OKX REST data and GitHub Actions, without Cloudflare paid processes.

## Next phase

Independently define and test confirmed BOS/CHOCH, live POI/IFVG overlap, retest chronology, and paper entry risk checks **before** any claim of a fully validated tradable setup. Paper statistics require real independently validated entries and subsequent price data.
