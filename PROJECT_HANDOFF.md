# BTC Intelligence System — PROJECT HANDOFF / SINGLE SOURCE OF TRUTH

> Last consolidated: 2026-11-26 (Europe/Warsaw). Maintained jointly with the user during active ChatGPT project work.
> IMPORTANT: This document is a persistent technical handoff, not proof of live deployment or successful trading. Review live outputs and GitHub Actions on each new session.
> Repository: `ivanovmaksim4646/-BTC-Intelligence-System.` — **the final period in the repository name matters**; default branch `main`.

## 1. Purpose and operating agreement

Build a mostly autonomous, **read-only, BTC-only futures market intelligence and ICT/CRT research system** that gathers trustworthy public order flow, market structure and liquidity observations, validates setup sequences, maintains paper-only performance statistics, and supports concise Ukrainian morning (08:15 Poland) and pre-New-York (13:45 Poland) reports and exceptional alerts. Live trading / exchange order execution is **out of scope**.

User requirements discussed across chats:
- **Free sources and free tiers first**. Do not buy Cloudflare Workers Paid, premium market-data providers, or subscriptions without explicit new user approval. Assess free-tier constraints before proposing deployment.
- Focus on BTC perpetuals, especially OKX BTC-USDT-SWAP for same-venue evidence. Kraken Spot/Futures are separate inputs, never a substitute for OKX futures evidence. Binance/BingX/TradingView inputs must be explicitly venue-identified.
- M5, M15, H1, H4, and where independently supported D1. ICT concepts: swings HH/HL/LH/LL, sweep, BOS, CHOCH/Shift, FVG/IFVG, OB, HTF POI, QM retest, PDH/PDL, PMH/PML, IB/ADR, sessions/Kill Zones, and opposing liquidity targets. **Do not mark unimplemented concepts as implemented**.
- Monitor bid/ask book, wall persistence, futures/spot Delta and CVD **separately where genuinely measured**, volume, OI and OI change, funding, mark/index premium, basis, volatility (BVOL24 where available), BTC.D, TOTAL1/2/3, stablecoin dominance/supply, ETF flows and macro announcements. External enrichment requires independent fresh verification.
- Every metric must have venue, timestamp, coverage, confidence/quality of evidence and freshness. Absent or partial measurements remain null/unknown. Never turn resting orders into executed trades, a snapshot into a liquidation heatmap, or page-level signed trade volume into full-interval CVD.
- Report succinctly in Ukrainian, Poland timezone; distinguish confirmed facts from inference, what changed since prior report, Plan A/Plan B, Long/Short/NO TRADE only when justified, entry conditions, invalidation and targets. Never invent probabilities, fill prices, recent macro prints or live signals. Preferred iPhone notifications; short alert copy, avoid repeating stale news.
- Data collection, analysis, alerts and trading execution are distinct layers. A GitHub green run is not proof of continuous market coverage or viable entries.

## 2. Verified repository inventory (2026-11-26)

### Main collectors, infrastructure and ingestion
- `.github/workflows/btc-intelligence.yml`; `src/collector.py`; `src/market_analysis.py`; `src/structure.py`; `src/setup_candidates.py`; `src/system_health.py`.
- `worker.js`, `wrangler.jsonc`; `cloudflare/` (OKX WS canary/flow pilot sources and tests); TradingView webhook workflow `.github/workflows/tradingview-intelligence.yml`.
- TradingView scripts: `tradingview/BTC-Intelligence-H1-InsideBar-M5.pine`, `tradingview/BTC-Intelligence-ICT-M5-v2.pine`. A script existing or tests passing **do not prove** TradingView alert activation or delivery.
- Historical/current: `data/BTC-intelligence-current.json`, `data/BTC-intelligence-history.csv`, `data/BTC-orderbook-history.jsonl`, `data/BTC-system-health.json`, `data/BTC-scheduler-health.json`, `data/BTC-tradingview-events.jsonl`.
- GitHub Actions triggers and Cloudflare credentials must be checked via current runs. **Never store PAT, Cloudflare tokens, webhook secrets or private keys in this file.**

### OKX modules already present in repository (not necessarily signal-ready)
- `src/okx_futures_candles.py`, `src/okx_futures_orderflow_v1.py`, `src/okx_flow_coverage_v1.py`, `src/okx_derivatives_context_v1.py`.
- `src/okx_liquidity_history_v1.py`, `src/okx_wall_persistence_v1.py`, `src/okx_liquidity_intelligence_v1.py`, `src/okx_market_context_v1.py`.
- `src/okx_poi_qm_v1.py`, `src/okx_entry_evidence_gate_v1.py`, `src/okx_setup_validator_v1.py`, `src/okx_outcome_tracker_v1.py`.
- Also risk/confluence/research: `src/risk_engine_v1.py`, `src/risk_engine_v2_okx.py`, `src/setup_confluence_v1.py`, `src/rr_statistics_v1.py`, `src/rr_outcome_research_v1.py`, `src/strategy_models_v1.py`; related `tests/` and GitHub workflows. Presence of files is not independently validated quality or production readiness.

### Existing detailed reference documents — read before changing respective areas
- `README.md` — system overview, limits, Cloudflare dispatch/Tv diagnostic checklist.
- `docs/okx-market-context-v1.md`
- `docs/okx-liquidity-intelligence-v1.md`
- `docs/okx-flow-coverage-stage1.md`
- `docs/okx-resting-liquidity-history.md`
- `docs/okx-wall-persistence-v1.md`
- `docs/okx-paper-outcome-tracker.md`
- `docs/okx-trades-all-ws-pilot-plan.md`
- `tradingview/OKX-migration-checklist.md`

## 3. Verified snapshot, NOT permanent live status (2026-11-26 around 14:10 UTC)

- `data/BTC-scheduler-health.json`: `event=workflow_dispatch`, `source=cloudflare`, `slot=2026-11-26T14:10:00Z`, run `45836275265`. Evidence of **one** Cloudflare-origin dispatch; not proof of uninterrupted five-minute cadence.
- `data/BTC-okx-market-context-v1.json`: closed OKX M5/M15/H1/H4 swing high/low classifications and matched sampled book/derivative context; overall `market_context=mixed`, `fresh_bos_or_choch=null`. Historical IFVG zones are descriptive only. No validated BOS/CHOCH, live POI retest, entry, TP or SL asserted.
- `data/BTC-okx-flow-coverage-v1.json`: sampled OKX REST page of 500 trades spanning 58.22 seconds, `status=sampled_only`; complete M5 Delta and complete CVD **null**, M5/M15/H1/H4 full coverage **false**. OI change is two verified snapshots, not a continuous intraperiod feed.
- `data/BTC-okx-setup-validator-v1.json`: 13 alerts inspected, 12 rejected/unverified due to venue mismatch, 0 new OKX observations, `NO_TRADE`.
- `docs/okx-paper-outcome-tracker.md`: outcome tracker accepts independently validated *paper-only* entries and follows future closed M5 OKX bars; do not fabricate entries/outcomes or confuse ambiguous same-candle TP/SL with confirmed fills.
- `docs/okx-liquidity-intelligence-v1.md`: book walls, OI, funding and premium are sampled observational context, **not** heatmap, absorption, spoofing proof, independent confirmations or trading signals.

## 4. Architecture and data integrity

`Public REST / exchange-specific market data` → `GitHub scheduled/Cloudflare-dispatched collection` → `validated raw data + timestamped history` → `venue-pure derivatives/liquidity and swing context` → `ICT event chronology / evidence gate (research)` → `independent validated paper entry (NOT YET PROVEN)` → `paper-only outcome tracker` → `report feed / user alerts`.

TradingView webhooks are **observations**, not executions or venue-agnostic truth. They need genuine TradingView alert delivery and exact OKX symbol/venue/timeframe matching before combination with OKX sources. No fabricated Delta/CVD or results; fail closed on stale, incomplete, misaligned or mixed-venue data.

For complete OKX Futures Delta/CVD, REST's capped recent-trades page does **not** cover M5/M15/H1/H4. A truly continuous public trades WebSocket pipeline would need documented free-tier feasibility, durable trade-ID deduplication, exchange timestamps, sequence/gap detection, reconnection, exact 5-minute bucket closure, watermark/replay and auditably complete aggregated windows. Experimental canary or short pilot != full coverage.

## 5. Priorities at handoff

1. **BOS/CHOCH + POI/IFVG + retest**: define causal, unambiguous closed-candle conditions and stage chronology. Verify same-venue OKX price history, higher-timeframe context, stale/mixed guards, and opposing-liquidity target; distinguish from existing descriptive swings and historical IFVG. Check present `okx_poi_qm_v1`, `okx_entry_evidence_gate_v1`, and related tests **before** writing duplicate logic.
2. **TradingView-to-OKX venue reconciliation**: check deployed alert instrument and live event payload; reject Binance/BingX events as OKX confirmations. Do not delete an existing working alert until new alert receipt is verified.
3. **Order flow completeness**: research truly free, reliable streaming or alternative honest coverage; remain `null`/partial where gaps exist. No Cloudflare paid upgrade without permission.
4. **Paper statistics only after evidence**: independent deterministic validator should produce authenticated paper entry journal; then outcome tracker computes R-multiples, win rate, expectancy with explicit sample size, ambiguity and cost assumptions. User values RR >=3 as a research preference, risk <=1% and leverage cap <=5 (not order settings).
5. **Observability**: check consecutive schedule slots, rate limits, last successful event timestamps, persistent logs, tests, and whether morning/pre-NY/alert automations actually ingest latest repository outputs. Never claim direct ChatGPT Work-to-main-chat data channel without confirming one.

## 6. Handoff and maintenance protocol — REQUIRED FOR FUTURE ASSISTANT SESSIONS

At the **start** of every session working on BTC Intelligence System:
1. Read this `PROJECT_HANDOFF.md`, `README.md`, relevant `docs/` and current code/data/workflow outputs. Explicitly separate repository state from user conversation memory.
2. Identify exactly what was last finished, what is verified live, what is only implemented/tested, what is blocked and what comes next.
3. Implement scoped task; test; inspect evidence. Avoid gratuitous rewrites. Do not assert success without a verified commit / test / resulting data.
4. **After each completed project task, update this same file in GitHub**: update verified state, decisions, key files, test/run evidence and timestamp; add one concise dated entry in the Change Log. Update accompanying feature docs when needed. Use a single logical commit when feasible.
5. The assistant can perform updates **while an active chat/task provides GitHub access**; it cannot guarantee autonomous updates after the chat ends, during unrelated conversations, or if tools/permissions are unavailable. If it cannot update GitHub, explicitly disclose and prepare a copyable handoff.
6. Protect secrets and privacy. Do not store passwords, PATs, personal identifiers, account financial balances or private user details. Only project-relevant requirements and architecture belong here.
7. Do not overwrite or erase historical decisions or prior log entries to disguise changes. Correct inaccuracies with dated amendments.

### Recommended change-log entry format
`YYYY-MM-DD HH:MM Europe/Warsaw | Task | Files/commits | Tests/real evidence | Known gaps | Next`

## 7. Change log

- **2026-11-26 | Persistent handoff created** | Consolidated user requirements and historical project decisions with verified repository tree and OKX data/docs. Last observed Cloudflare-origin dispatch was 14:10 UTC. No new trading signals or complete Delta/CVD implied. Next: independently verify and extend BOS/CHOCH → POI/IFVG → retest in the existing OKX pipeline.

- **2026-11-26 | Continuity checkpoint after Market Context v1** | Prior session reported 298 passing tests and successful run 45835969206 (test count not independently rechecked in this checkpoint). Repository inspection confirms existing OKX POI/QM and entry evidence gate; do not rebuild them. TradingView journal contains a real OKX bearish FVG received 14:00:30 UTC, alongside legacy BingX events. At 14:15 UTC the entry gate still reported zero candidates and no same-bar independently corroborated OKX alert. Market Context v1 still sets fresh_bos_or_choch to null. Next: audit existing structure and confluence algorithms, add missing causal BOS/CHOCH integration only, then validate chronological setup integration with existing POI/QM and risk gates. No paid services or live execution.

- **2026-11-26 | OKX BOS/CHOCH candidate integration (feature branch, pending CI)** | Reused existing venue-neutral `structural_shift` and `continuation_bos` from `src/structure.py` on validated OKX M5/M15/H1/H4 bars. Added first-cross filter, source/timeframe/close metadata, six regression tests and updated documentation. Code commit `d69444ca003bf82eada232fd18c4c3a3837ae45d`; CI configuration commit `61c872b61e703f73af1c78f6be5586088904ee78` on `feature/okx-bos-choch-candidates`. Not merged or production-verified; full regression result pending. Existing NO_TRADE and paper-entry gate unchanged. Next: verify CI, merge only after passing, then integrate chronology with existing POI/QM gate. No paid services added.

- **2026-11-26 | OKX BOS/CHOCH candidate extension merged** | Full GitHub CI run [45838201435](https://github.com/ivanovmaksim4646/-BTC-Intelligence-System./actions/runs/45838201435) passed **304 Python tests** (six added). Market Context smoke test: structure_and_sampled_liquidity, mixed HTF/LTF, liquidity present, warnings empty. PR #25 merged into main, commit `35689a8d1c56cfac8f6d650afe46b1ce76034fbc`. Main source verified. Regular collector integration already exists; fresh main collector run after merge not yet verified. BOS/CHOCH remain algorithmic candidate observations, not entries; no change to entry gate or NO_TRADE. Next: verify subsequent main sync, integrate chronological BOS/CHOCH evidence with existing POI/QM retest validator without weakening independent evidence gates.

- **2026-11-26 | OKX setup chronology extension staged** | Branch `feature/okx-setup-chronology-v1`, latest commit `645ceac731ca0ac541239152d3cd8d3b2c708b0c`. Existing paper gate now requires causal same-direction M5 BOS/Shift between QM head and structural extreme, no later opposite break before retest; HTF FVG/IFVG availability is determined from closed historical prefixes. Added far-edge close invalidation and per-evaluation directional retest deduplication; existing venue, retest, target and risk safeguards retained. These stricter experimental rules need sample validation. Initial branch CI run 45838685675 passed; latest commit CI not yet verified. Main unchanged; no live signal or production validation claimed. Next: verify latest CI and merge only after passing; then verify main sync and review paper sample availability.

- **2026-11-26 | OKX setup chronology merged** | PR #26 merged to main as `dc398bc7067db640b9e833e0b598b11150bb9134`; main code verified. Latest [CI run 45838777101](https://github.com/ivanovmaksim4646/-BTC-Intelligence-System./actions/runs/45838777101) passed 312 tests (8 added) and live OKX smoke check: NO_TRADE, zero new paper entries, missing same-bar independently corroborated OKX TV alert; outcome tracker zero new outcomes, no warnings. Conservative first-cross chronology, FVG/IFVG availability, invalidation and per-evaluation dedup rules are experimental; no performance claimed. Regular scheduled production run after merge remains to be verified. Next: review main sync, diagnose live alert/candle temporal matching and actual paper candidate coverage without relaxing provenance or fabricating entries.

- **2026-11-26 | TradingView/OKX synchronization audit and evidence diagnostics merged** | At 14:25 UTC, 15 TV alerts: 13 BingX withheld; 2 OKX bearish FVG observations independently matched exact OKX close prices (60850.2, 60792.2), journal confirmed. No full chronological setup on matching latest close; no paper entries. Added per-stage evidence funnel counts, validated matched three-candle OHLC continuity, unique matched-event diagnostics and persistent directional close dedup. PR #27 merged as `c64a24a323ccdf9d7a33913ad192af1e8a0b2b4c`; CI run 45839288462 passed 317 tests and live OKX smoke check (NO_TRADE, zero entries/outcomes). Same-close requirement remains; no retroactive paper entries. Next: verify subsequent main sync with diagnostics, then consider causal historical alert replay in separate research journal to quantify missing same-close coverage and setup frequency, without fabricating trades or mixing with forward paper statistics.

- **2026-11-26 | Historical Replay v1 merged** | PR #28, merge `e6dfbca5b22f928756a279aa711de9f0f15be3cc`; CI run 45839610353 passed **323 tests** and actual historical snapshot replay. 299 M5 candles (25 Nov 13:30 UTC to 26 Nov 14:25 UTC), 30-bar warmup, 270 evaluated closes, 2 genuine matched OKX alerts, 268 closes without matched alert, 6 direction-matched confirmed QM candidate paths, zero first retests and zero historical hypotheses. 981 QM counts are repeated per-bar observations, NOT unique patterns. No valid RR/Win Rate/Expectancy estimate. Separate artifact, manual workflow, no forward-paper writes or new recurring compute. The replay simulates historical closed-bar availability and receipt within 360s, not actual historical execution. Next: extend verified historical OHLC and measure alert-independent setup coverage in a separately labeled research mode without fabricating TradingView events or weakening forward gate; assess samples before tuning rules.
