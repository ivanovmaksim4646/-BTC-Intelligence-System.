# Backtest v5 acceptance criteria

365 days, no trade quota, $1000 initial balance, 1% risk including estimated costs, one open position. Research only; no production changes.

## Mandatory Shift context
Accept a directional Shift only after a causally confirmed liquidity sweep (internal and external tagged separately), or at a valid MTF/HTF POI or Key Level touched before the Shift. Reject airborne shifts. Require displacement, closed-candle structure confirmation, and structural invalidation. POI must be formed before touch and not invalidated before entry. Record exact evidence timestamps and reject missing evidence. Test H1/H4/D1/W1/MN1 POIs separately; tag FVG, IFVG, QM and key levels. Define key level and displacement thresholds explicitly before evaluating outcomes. Do not equate BOS with reversal Shift without a separate label.

## Reporting
Allow net structural RR >=1; report non-overlapping planned net RR bands [1,2), [2,3), >=3, and separate fixed net 1R/2R/3R counterfactual exit scenarios; never pool the same entry three times. Report unique combined portfolio, wins/losses, net expectancy, P&L, profit factor, drawdown, skipped overlapping entries and unresolved outcomes. Slice by POI timeframe/type, sweep type, Shift, session and direction; disclose overlaps in attribution. Compare same dates and holdout; independent validation remains necessary. No invented historical CVD/Delta/OI.

Status: specification only; implementation and run not yet verified.

## Final approved amendments
MTF H1/H4; HTF D1/W1/MN1; LTF M15 primary, M5 separately evaluated. Test contextual Shift, MTF/HTF POI + LTF QM, K-level confirmations, and Inside Bar/range deviation with sweep and re-entry opposite the false breakout. Separate trend continuation after correction from countertrend correction; label market direction separately from executed order flow. Count long, short, neutral and missing factors at each entry using only timestamped data available then: spot/futures CVD, delta, volume, OI, funding, basis, order book, liquidation/liquidity and other connected feeds where historical coverage is verified. Do not substitute current readings or candle proxies for actual executed flow. Report coverage, correlated factors, and performance by confluence score; no arbitrary majority entry rule. User authorizes v5 run; implementation and dispatch not yet verified.
