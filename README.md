# BTC Intelligence System

Read-only BTC futures market-intelligence collector and structure monitor. **It does not execute trades and has no verified automated entry signals.**

## Components

| Component | File / workflow | What it actually does |
| --- | --- | --- |
| Kraken Spot / Futures | `src/collector.py`, `btc-intelligence.yml` | Delta, window CVD change, volume, OI, funding, basis, order book |
| Order-flow observations | `src/market_analysis.py` | Venue-specific buying/selling pressure, divergence classification |
| Closed-candle structure | `src/structure.py` | Inside bars, sweeps, FVG, algorithmic Shift/BOS candidates on Kraken Spot |
| Watchlist | `src/setup_candidates.py` | Conservative monitoring candidates, **not** confirmed entries |
| System diagnostics | `src/system_health.py` | Freshness and provenance; cannot verify Cloudflare internals |
| TradingView intake | `worker.js` → `tradingview-intelligence.yml` | Receives validated alerts, dispatches GitHub workflow, persists events |
| Cloudflare 5-minute trigger | `wrangler.jsonc`, `worker.js` | Cron + Durable Object, **requires valid GitHub dispatch token** |

Outputs: `data/BTC-intelligence-current.json`, `data/BTC-analysis-current.json`, `data/BTC-structure-current.json`, `data/BTC-setup-candidates.json`, `data/BTC-system-health.json`, and `data/BTC-scheduler-health.json`. TradingView intake will create `data/BTC-tradingview-events.jsonl` only after a real event is received.

### Critical data interpretation

- Window `cvd_change` **equals** the window Delta; it is not independent confirmation or absolute running CVD.
- Kraken Spot candles are **not** verified Binance/BingX futures ICT structure.
- Snapshots of book walls can be cancelled; they do not prove executed liquidity or a liquidation heatmap.
- A GitHub Action marked success does **not** prove five-minute cadence, Cloudflare dispatch, or TradingView webhook delivery.
- `fully_operational_confirmed` is conservative diagnostic evidence, **not** an uptime SLA or authorization to trade.

## Running automated checks

Main workflow: [BTC Intelligence Sync](../../actions/workflows/btc-intelligence.yml).

Run tests locally: `python -m unittest discover -s tests -v`.

Regenerate the local health snapshot: `python src/system_health.py`.

The main workflow writes health diagnostics on every attempted collection and commits its data when collection succeeds. The GitHub schedule is a best-effort fallback and cannot be relied on for precise 5-minute data.

## Restoring Cloudflare → GitHub dispatch / TradingView

If TradingView shows **502 Bad Gateway** and Cloudflare logs report **GitHub dispatch failed 401**, the GitHub PAT used by the Cloudflare Worker is invalid, expired or mismatched. A successful GitHub-only scheduled collector run does not fix this.

**Required human action** (never paste token values in issues, code, chat or screenshots):

1. Generate or regenerate a **fine-grained GitHub PAT** for only this repository with **Actions: Read and write** and **Metadata: Read-only**; securely copy its one-time visible value.
2. Add it in repository **Settings → Secrets and variables → Actions**, with secret name **`BTC_GITHUB_DISPATCH_TOKEN`** (replace existing value if present). The GitHub plugin does not provide a secret-editing API.
3. Run **Deploy BTC Cloudflare scheduler** from repository Actions. The deployment first validates the PAT against GitHub; after success it deploys the Worker and syncs it to Cloudflare secret **`GITHUB_DISPATCH_TOKEN`**.
4. Verify a **new** run has `event: workflow_dispatch` and `source: cloudflare` in `data/BTC-scheduler-health.json`. Then verify a real TradingView alert creates `data/BTC-tradingview-events.jsonl` and **no longer shows 502**.
5. Check several consecutive 5-minute slots and Cloudflare logs before claiming autonomous 5-minute reliability.

If the PAT web page returns **HTTP 500 immediately after regeneration**, it may have rotated without displaying the value. Do not repeatedly regenerate blindly. Prefer a stable authenticated desktop browser session when available.

### Secrets

- GitHub Actions repository secret `BTC_GITHUB_DISPATCH_TOKEN`: PAT for GitHub workflow dispatch.
- GitHub Actions repository secret `CLOUDFLARE_API_TOKEN`: deploy credential, **not the GitHub PAT**.
- Cloudflare Worker secret `GITHUB_DISPATCH_TOKEN`: synchronized by the deployment workflow; not stored in source control.

## Known limitations

A liquidation heatmap, Binance/BingX verified order-flow, ETF feeds, macro data, comprehensive PDH/PDL/IB/ADR, validated trade entries/stops/targets, and production-grade backtesting are **not** supplied by the collector. The TradingView Pine script currently emits H1 Inside Bar / M5 Sweep observations; it does not provide continuous candles or all ICT objects. Never imply unavailable feeds are present.


## TradingView ICT M5 v2 — activation checklist

The existing **BTC Intelligence — H1 Inside Bar / M5 Sweeps** alert remains unchanged and its v1 webhook payload continues to be supported.

New source: [tradingview/BTC-Intelligence-ICT-M5-v2.pine](tradingview/BTC-Intelligence-ICT-M5-v2.pine)

1. In TradingView Pine Editor, create a **new script**, paste the source and compile it on **BTCUSDT perpetual M5**. The code was not compiled in TradingView by GitHub CI: GitHub validates Python and Worker JS only.
2. Create a **new independent alert** from this v2 indicator, condition **Any alert() function call**, once per bar close. Do not delete the existing v1 alert yet.
3. Set the same existing Cloudflare webhook URL ending in **/tv-webhook**, and enable the alert. The endpoint allows only TradingView webhook origin IPs and strictly validates a BTC symbol, M5, timestamp and narrow payload schema.
4. Wait for a real v2 event. Verify webhook is delivered (not 400 or 502), then check [data/BTC-tradingview-events.jsonl](data/BTC-tradingview-events.jsonl) for an event with `source: btc-intelligence-tv-v2`.
5. Compare the specific event candle and price on TradingView. Only after real events pass end-to-end can v2 be considered live.

**v2 event names:** `m5_bullish_bos`, `m5_bearish_bos`, `m5_bullish_shift`, `m5_bearish_shift`, `m5_bullish_fvg`, `m5_bearish_fvg`, `m5_sweep_pdh`, `m5_sweep_pdl`. The script emits only one prioritized event per closed M5 candle. Confirmed pivots use a 2-left/2-right lookback. BOS/Shift are simplified algorithmic *candidates*, not fully validated ICT structure, and gaps are not independently verified as unfilled/mitigated institutional FVG. These v2 events are observations, not executable entries or probabilities. Correlation with Kraken Spot/Futures Delta and OI must be validated separately and must not be inferred solely from webhook receipt.

Live CI: [TradingView v2 tests](../../actions/workflows/tradingview-v2-tests.yml) checks legacy and new payload validation plus `node --check worker.js`. [Deploy Cloudflare](../../actions/workflows/deploy-cloudflare.yml) deploys Worker changes.
