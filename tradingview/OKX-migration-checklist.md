# TradingView → OKX BTC Futures migration (manual chart-side step)

## What is already automated
- Existing /tv-webhook and Durable Object delivery remain unchanged.
- GitHub validates alerts and commits them to `data/BTC-tradingview-events.jsonl`.
- On the next BTC Intelligence Sync, `src/okx_setup_validator_v1.py` compares **only** `OKX:BTCUSDT.P` observations with closed OKX BTC-USDT-SWAP M5 candles.
- The append-only `data/BTC-okx-setup-observations-v1.jsonl` is **not a trade journal**. It contains evidence-limited event observations. It **does not** insert entries into `BTC-rr-validated-outcomes-v1.jsonl`.
- BingX alerts remain receivable and archived, but are never promoted to OKX observations or trades.
- All entries, stops, targets and trading signals remain disabled pending independent setup confirmation and forward validation.

## Change required in the TradingView account
An external GitHub change **cannot change the symbol of a previously created TradingView alert**. In TradingView:

1. Open a chart of **OKX BTCUSDT Perpetual Swap Contract**, ticker `OKX:BTCUSDT.P`, and set interval **5m**.
2. Add the existing indicator `tradingview/BTC-Intelligence-ICT-M5-v2.pine` to that chart.
3. Create a **new alert**: condition **Any alert() function call**, webhook URL **unchanged** from the existing alert, alert **enabled**.
4. Verify the JSON message emitted contains `"symbol":"OKX:BTCUSDT.P"`; old `BINGX:BTCUSDT.P` alert may be disabled only **after** a successful live OKX end-to-end event.
5. The old indicator version and webhook schema remain unchanged. Do **not** enter credentials or tokens into the alert message.

## Verification
- New alert is visible in `data/BTC-tradingview-events.jsonl` with OKX symbol.
- The matched closed OKX M5 bar is identified in `data/BTC-okx-setup-validator-v1.json`.
- A matching FVG may appear as `observed_not_trade` in the OKX journal, while other structure events remain price-consistency observations only.
- Any price/time mismatch is withheld rather than used as a trade entry.
- No automatic capital allocation or live orders are allowed.
