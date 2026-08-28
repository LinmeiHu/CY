# V12 Price-Only Swing Carrier Viability Study

## Decision

The discovery-only procedure froze **A_PULLBACK_RECLAIM** before validation or holdout construction. Its final classification is **VALIDATION_ONLY**. A robust price-only carrier was not established, so chip-overlay retesting remains gated.

This is a research-only result on the frozen 500-symbol research scope. It neither modifies production strategy code nor authorizes the 3,941-symbol build.

## Frozen provenance and protocol

- Frozen candidate artifact: `3913c3f839c9a5a9f682e47ff256be53a5a8395e371b34df019959692e7dc82a` (47,518 symbol-days, 5,671 deterministic episodes, 494 represented symbols).
- Registered daily PIT price/execution artifact: `1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62`.
- The reconstructed corporate-action analysis coordinate matched every frozen candidate close exactly.
- No chip or temporal feature artifact was opened. Those data had no role in candidates, carrier choice, entry, size, holding, exit, or portfolio priority.
- Discovery ends 2020-04-30; validation is 2020-05-01 through 2020-08-31; holdout is 2020-09-01 through 2020-12-31. Open trades are terminal-marked at each split boundary and are not counted as completed trades.
- The carrier family, costs, risk rules, portfolio rules, selection rule, viability gates, and diagnostic sensitivities were serialized before discovery evaluation. Validation and holdout trades were built only after `primary_carrier_freeze.json` was written.

## Pre-registered carriers and execution

The three conceptually distinct carriers are MA5 pullback reclaim, prior-three-high local breakout, and medium-trend resumption. Each has a five-session signal expiry, then at most three source sessions for a legal buy open. Signals use closing-bar information; intents are scheduled for a subsequent session; fills occur only at legal opens. Suspensions, invalid observations, and exchange limit blocks fail closed.

All use a 2×ATR14 close-based hard-risk threshold, next-legal-open exits, MA10 ordinary trend exit, 2R/MA5 profit protection, and a 20-session maximum hold. Diagnostic 1.5× and 2.5× ATR runs were pre-registered. Base round-trip costs comprise 3 bps commission and 0.2 bps transfer fee on each side, 10 bps sell stamp duty, and 5 bps slippage on each side; the stressed case raises commission to 5 bps and slippage to 10 bps.

The portfolio starts at 1.0, has ten equal-weight 10% slots, no leverage, no same-symbol overlap, exits before same-open entries, and uses deterministic future-independent priority.

## Discovery freeze

The rule first requires positive discovery trade and portfolio economics, no worse than 25% drawdown, stressed-cost positivity, positive expectancy at both ATR diagnostics, and at least 75 completed trades. It ranks by the worst PF across those discovery diagnostics—not headline return. The selected worst-case discovery PF was 0.876; fallback selection was used.

## Canonical carrier results

| Carrier | Split | Trades | PF | Expectancy | Net portfolio | Max DD | Sharpe | Exposure | Terminal MTM share | Top-10 winner share | Top symbol share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_PULLBACK_RECLAIM | discovery | 432 | 0.947 | -0.09% | -2.41% | -8.15% | -0.431 | 23.38% | 148.36% | 27.94% | 4.32% |
| A_PULLBACK_RECLAIM | holdout | 769 | 0.762 | -0.56% | -8.26% | -19.81% | -0.974 | 92.84% | 162.03% | 26.68% | 8.82% |
| A_PULLBACK_RECLAIM | validation | 1110 | 1.453 | 0.94% | -2.05% | -15.97% | -0.103 | 92.22% | 52.21% | 15.19% | 4.19% |
| B_LOCAL_BREAKOUT | discovery | 349 | 0.503 | -1.30% | -9.98% | -13.10% | -2.324 | 22.79% | 18.07% | 38.82% | 7.12% |
| B_LOCAL_BREAKOUT | holdout | 336 | 0.771 | -0.65% | 6.48% | -15.10% | 0.895 | 87.04% | 266.01% | 38.63% | 9.45% |
| B_LOCAL_BREAKOUT | validation | 554 | 1.332 | 0.90% | -5.63% | -15.03% | -0.472 | 88.48% | 21.21% | 21.78% | 5.95% |
| C_TREND_RESUMPTION | discovery | 88 | 0.533 | -1.56% | -8.23% | -9.80% | -1.980 | 22.40% | 2.63% | 71.26% | 11.19% |
| C_TREND_RESUMPTION | holdout | 205 | 0.632 | -1.33% | 7.16% | -14.15% | 0.939 | 85.00% | 238.04% | 60.40% | 11.87% |
| C_TREND_RESUMPTION | validation | 503 | 1.119 | 0.36% | 8.00% | -15.01% | 0.904 | 88.99% | 27.36% | 25.09% | 5.18% |

Completed-trade metrics exclude terminal-open trades. Portfolio net return includes terminal marking; the separate realized-versus-terminal table identifies endpoint dependence. Exact funnels, costs, holding distributions, MFE/MAE, giveback, winner-tail exclusions, per-symbol contributions, regimes, and price-only winner/loser attribution are in the machine-readable outputs.

### PF / portfolio reconciliation

- **B_LOCAL_BREAKOUT / holdout:** 6.48% marked portfolio return coexists with PF 0.771 because realized portfolio P&L was -10.76% while terminal unrealized P&L was 17.25%. This is endpoint-dependent, not positive completed-trade economics.
- **C_TREND_RESUMPTION / holdout:** 7.16% marked portfolio return coexists with PF 0.632 because realized portfolio P&L was -9.89% while terminal unrealized P&L was 17.05%. This is endpoint-dependent, not positive completed-trade economics.

The primary carrier's holdout hard-risk sensitivity was: 1.5× ATR: expectancy -0.55%, PF 0.765; 2.0× ATR: expectancy -0.56%, PF 0.762; 2.5× ATR: expectancy -0.51%, PF 0.780. The negative sign persisted across the complete pre-registered 1.5×–2.5× ATR range, so the viability conclusion is not an artifact of the primary 2× choice.

## Classification

| Carrier | Primary | Classification | Validation trade edge | Holdout trade edge | Stressed-cost robust | Concentration |
|---|---:|---|---:|---:|---:|---:|
| A_PULLBACK_RECLAIM | YES | VALIDATION_ONLY | YES | NO | NO | MIXED |
| B_LOCAL_BREAKOUT | NO | VALIDATION_ONLY | YES | NO | NO | MIXED |
| C_TREND_RESUMPTION | NO | VALIDATION_ONLY | YES | NO | NO | MIXED |

## Required answers

1. **Can P_PRICE_PULLBACK_20 support a positive-expectancy price-only swing system?** Not established by this pre-registered study.
2. **Which carrier survives holdout?** No carrier earned ROBUST_POSITIVE; A_PULLBACK_RECLAIM was the discovery-frozen primary and classified VALIDATION_ONLY.
3. **Positive completed-trade performance?** No; holdout net expectancy was -0.56% across 769 completed trades.
4. **Realized PF above 1?** No; 0.762.
5. **Positive after realistic costs?** No at base costs; stressed-cost robustness is NO.
6. **Material terminal MTM dependence?** NO; realized P&L -21.65%, terminal unrealized 13.39%.
7. **Excessive trade/symbol concentration?** Gate MIXED; top holdout symbol share 8.82%, largest positive validation/holdout month shares 50.03% / 100.00%.
8. **Enough trades?** YES; the pre-registered minimum is 100.
9. **Stable discovery → validation → holdout?** Discovery/validation/holdout expectancy was -0.09% / 0.94% / -0.56%; PF was 0.947 / 1.453 / 0.762.
10. **Legitimate baseline for a later V3 soft-overlay test?** NO.

## Failure diagnosis / next research gate

Failure is best classified as **market/regime dependency with unresolved exit/holding design**, not primarily transaction costs: all three entry families were positive on validation but negative on holdout completed trades, and the primary remained negative even at zero costs and across all pre-registered ATR rules. This does not prove the frozen candidate architecture is useless. The evidence does not justify chip filters, broad parameter search, production implementation, or full-market expansion. The smallest next question is whether one independently specified exit/holding architecture can improve MFE capture without changing the frozen candidates or entry family; that question must be separately pre-registered.

## Hard gates

`CANDIDATE_UNIVERSE_UNCHANGED: YES`
`CHIP_DATA_USED_IN_CARRIER_SELECTION: NO`
`PRICE_CARRIER_FAMILY_PRE_REGISTERED: YES`
`PRIMARY_CARRIER_FROZEN_BEFORE_VALIDATION: YES`
`PRIMARY_CARRIER_FROZEN_BEFORE_HOLDOUT: YES`
`HOLDOUT_COMPLETED_TRADE_EXPECTANCY_POSITIVE: NO`
`HOLDOUT_REALIZED_PROFIT_FACTOR_ABOVE_1: NO`
`HOLDOUT_NET_PORTFOLIO_RETURN_POSITIVE: NO`
`POSITIVE_RESULT_DEPENDS_MATERIALLY_ON_TERMINAL_MTM: NO`
`HOLDOUT_TRANSACTION_COST_ROBUST: NO`
`HOLDOUT_SAMPLE_SIZE_ADEQUATE: YES`
`PROFIT_CONCENTRATION_ACCEPTABLE: MIXED`
`ROBUST_PRICE_ONLY_SWING_CARRIER_FOUND: NO`
`SAFE_TO_RETEST_V3_AS_SOFT_OVERLAY: NO`
`SAFE_TO_DESIGN_PRODUCTION_SWING_STRATEGY: NO`
`SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941: NO`
