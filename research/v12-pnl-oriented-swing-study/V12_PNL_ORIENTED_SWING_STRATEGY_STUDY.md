# V12 P&L-Oriented Swing Strategy Study

## Executive answer

The exact `P_PRICE_PULLBACK_20` universe was frozen before trade evaluation: 47,518 candidate symbol-days, 5,671 deterministic episodes, 494 represented symbols, and date coverage 2020-04-02 through 2020-12-31. The primary carrier selected on discovery only was `T1_CLOSE_STRENGTH`.

No, the price-only carrier did not meet the strict out-of-sample profitability rule requiring positive after-cost validation and holdout portfolio returns and Profit Factor above one in both. Validation net return was 10.87% with Profit Factor 1.496; holdout net return was -16.03% with Profit Factor 0.603.

The strongest holdout net-return delta was `P6_DETERIORATION_DERISK` at 22.42%; the strongest maximum-drawdown delta was `P2_CANONICAL_PERSISTENCE` at 9.54%. These are measured against the same candidate, price, signal, execution, cost, and capacity contracts. The evidence classification is `MIXED` and V3 complexity is `MIXED` under the predeclared economic thresholds.

No production code, V3 semantics, frozen chip artifact, or authoritative lifecycle/entry/exit ledger was modified. No 3,941-symbol build was started.

## Frozen candidate universe

- Definition fingerprint: `b796131a31eadd0283d154c08befa15fef91721fb501102a00adebd9d8e55cba`
- Source commit: `6bd5ab91d7fb0aefa07e913e241d58041920eac1`
- Frozen research universe: 500 symbols; 494 have candidates
- Candidate symbol-days: 47,518
- Candidate episodes: 5,671
- Episode duration: p25 1.0, median 4.0, p75 12.0, maximum 63 sessions
- Chronological splits: discovery through 2020-04-30; validation 2020-05-01 through 2020-08-31; holdout from 2020-09-01

Episode end and full duration are retrospective reporting fields only. Entry generation uses only the episode ID, onset, current PIT age, and contemporaneous panel fields.

## Price-only carrier selection

The finite family and selection rule were fixed in code before result generation. Only discovery trades determined the carrier.

| Template | Discovery trades | Discovery Profit Factor | Mean net return | Selected |
|---|---:|---:|---:|---|
| `T1_CLOSE_STRENGTH` | 573 | 1.266 | 0.61% | YES |
| `T2_RECLAIM_PRIOR_3_HIGH` | 286 | 0.533 | -1.61% | NO |
| `T3_TREND_RESUMPTION` | 75 | 0.413 | -2.72% | NO |

Every signal is formed after the daily observation is available. Entry and exit intents execute only at a later legal open. Buy/sell blocked opens are skipped, entry intents expire after five source sessions, and exit intents remain pending until a legal sell open. Economic prices use the governed corporate-action coordinate; raw and modeled fill prices remain in the trade artifact.

Costs are 3 bps commission each side, 0.2 bps transfer fee each side, 10 bps sell stamp duty, and 5 bps slippage each side. The normalized portfolio has ten slots, no leverage, 10% baseline allocation, and deterministic price-strength/symbol/trade-ID tie-breaking.

## P0 results

| Split | Net return | Max drawdown | Sharpe | Profit Factor | Trades |
|---|---:|---:|---:|---:|---:|
| Discovery | -3.85% | -12.49% | -0.724 | 1.266 | 573 |
| Validation | 10.87% | -12.61% | 1.540 | 1.496 | 1017 |
| Holdout | -16.03% | -20.16% | -2.640 | 0.603 | 915 |

Full portfolio and trade metrics, including gross return, Sortino, Calmar, drawdown duration, exposure, turnover, costs, tail quantiles, holding time, MFE, MAE, capture, and giveback, are in `portfolio_metrics.csv` and `trade_metrics.csv`.

The holdout portfolio finished with 10 positions marked at governed close prices because no future legal interval exists in the frozen source. No end-of-sample liquidation fill is fabricated. Portfolio return includes those marks; completed-trade Profit Factor excludes them.

## Isolated chip roles

| Isolated role | Holdout net return | Delta vs P0 | Max drawdown | Sharpe | Trade Profit Factor |
|---|---:|---:|---:|---:|---:|
| `I_CONFIRMATION_ONLY` | -2.94% | 13.09% | -13.41% | -0.403 | 0.610 |
| `I_SIZING_ONLY` | -14.86% | 1.17% | -18.71% | -2.538 | 0.603 |
| `I_HOLDING_ONLY` | -16.54% | -0.52% | -20.87% | -2.673 | 0.616 |
| `I_DERISK_ONLY` | -15.60% | 0.43% | -19.77% | -2.560 | 0.602 |

Confirmation/filtering is the clearest isolated role: it improved holdout portfolio return by 13.09 percentage points and drawdown by 6.74 points, although the portfolio still lost 2.94% and trade Profit Factor remained below one. Sizing was a small secondary improvement. Healthy holding worsened holdout portfolio return and drawdown despite capturing additional return on some individual winners. The isolated deterioration response made only a small portfolio improvement and did not improve holdout trade Profit Factor. Thus the role answer is **confirmation first, bounded sizing second, with holding and de-risking still mixed**.

## Controlled ablation ladder

| Variant | Holdout net return | Max drawdown | Sharpe | Trade Profit Factor | Completed trades |
|---|---:|---:|---:|---:|---:|
| `P0_PRICE_ONLY` | -16.03% | -20.16% | -2.640 | 0.603 | 915 |
| `P1_TEMPORAL_CONFIRMATION` | -2.94% | -13.41% | -0.403 | 0.610 | 732 |
| `P2_CANONICAL_PERSISTENCE` | 4.07% | -10.62% | 0.721 | 0.519 | 233 |
| `P3_MASS_PROMINENCE` | -0.34% | -13.54% | 0.024 | 0.577 | 90 |
| `P4_CHIP_SIZING` | 2.93% | -14.01% | 0.566 | 0.577 | 90 |
| `P5_HEALTHY_HOLDING` | 4.50% | -14.16% | 0.791 | 0.663 | 90 |
| `P6_DETERIORATION_DERISK` | 6.40% | -14.16% | 1.077 | 0.680 | 90 |

`P2_CANONICAL_PERSISTENCE` and `P6_DETERIORATION_DERISK` produced positive marked portfolio returns after costs, including at 10 bps slippage per side. However, their completed holdout trade Profit Factors were 0.519 and 0.680; even the portfolio-admitted completed-trade Profit Factors were 0.943 and 0.862. Open terminal marks, capacity interactions, and exposure therefore matter to the positive portfolio result and prevent a simple claim that selected trades were independently profitable.

## Conditional V3 evidence

At entry, ensemble-ambiguous trades had mean net returns of 0.94% in validation and -1.06% in holdout. Valid-canonical trades had 2.56% and -1.73%, respectively. This yields `MIXED` for canonical validity and `MIXED` for ambiguity. Ambiguity is therefore treated as an observed structural condition, not assumed bullish or bearish and never supplied a fake base.

Entry mass and prominence thresholds are discovery-distribution medians (0.239785 and 0.0127406); they were not P&L-optimized. Level and deterioration roles remain separate. The full entry/candidate strata and in-position deterioration associations are in the feature-attribution artifact.

The entry-level mass and prominence buckets did not show monotone, replicated economics: all holdout buckets remained negative and prominence-high was not best. Combined 20% mass/prominence deterioration plus price confirmation occurred only 12 times in validation and 8 times in holdout; its holdout mean return was negative. Topology states were economically worse in downside incidence, but not reliable enough to encode as automatic sells: the combined split/merge/lost/transition stratum had 10.9% holdout large-loss incidence versus 5.0% for valid-canonical and 5.7% for ambiguity.

## Winner preservation and robustness

The isolated confirmation filter removed 20/60 holdout large losers while retaining 71/92 top-decile winners. The cumulative P6 ladder removed 57/60 large losers but retained only 6/92 top-decile winners. That opportunity cost is too high to call the cumulative filter robust winner-preserving evidence.

P6 remained positive at 10 bps slippage per side (5.64% holdout portfolio return), but robustness was inconsistent: one deterministic symbol half had negative incremental mean trade return, the September–October winner profit was highly concentrated, and high-volatility trades were materially worse. These checks drive the `MIXED` economic/complexity classifications and the `NO` full-market gate.

## Required final answers

1. **Does `P_PRICE_PULLBACK_20` support a viable price-only swing system?** No; see the validation/holdout rule and metrics above.
2. **Does V3 chip state contain incremental information conditional on identical candidates?** MIXED.
3. **Is V3 more valuable for filtering, sizing, holding, or de-risking?** Confirmation/filtering first; bounded sizing is a small secondary role; holding and de-risking remain mixed. The strongest cumulative holdout return variant is `P6_DETERIORATION_DERISK` and the strongest drawdown variant is `P2_CANONICAL_PERSISTENCE`.
4. **Does canonical-base validity improve trade economics?** MIXED.
5. **What is the economic meaning of ensemble ambiguity?** `MIXED` relative economic value; it remains regime-conditional structural uncertainty, not an automatic trade direction.
6. **Do mass/prominence levels help at entry?** NO.
7. **Does mass/prominence deterioration help after entry?** MIXED.
8. **Can chip information reduce large losers without deleting major winners?** MIXED; exact removed/retained counts are in `winner_preservation.csv`.
9. **Can chip health preserve winners and capture more MFE?** MIXED.
10. **Does chip-aware sizing improve risk-adjusted performance?** YES.
11. **Does any V3 overlay improve holdout net P&L after costs?** YES.
12. **Does any V3 overlay materially reduce holdout drawdown/tail risk?** YES for maximum drawdown; tail deltas are reported separately.
13. **Is V3 complexity economically justified?** MIXED.
14. **Is evidence strong enough to expand from 500 to 3,941 symbols?** NO.

## Reproducibility and scope

The runner verifies every governed predecessor hash, freezes the candidate parquet first, and then evaluates trades. Candidate regeneration after P&L is prohibited by contract. All machine outputs use deterministic ordering; their SHA-256 hashes are:

- `ablation_ladder.csv`: `5b89b57e45c90b40bed4238abf0246e390509581c9a7e172584c7ceb0267d34f`
- `baseline_template_comparison.csv`: `330dd537d50f3651e22b2965e5b703fe688182916e0ec27cf645909cfec0f6b9`
- `candidate_universe.parquet`: `3913c3f839c9a5a9f682e47ff256be53a5a8395e371b34df019959692e7dc82a`
- `chip_feature_trade_attribution.csv`: `5a335bd1e9ea40e131673b7ce4bf5b35a9938a327704358e4cc129fa0a3a6c3c`
- `chip_state_trade_stratification.csv`: `ff2c8f706b83a0beadb992a44a042ebf5c9170decee44e25a10502b42d66f26f`
- `overlay_comparison.csv`: `738145ce4f9488080706e1d816e9bd5f44c18f4129e814398a9e1ec8958d98d6`
- `portfolio_metrics.csv`: `1a1aa2de6fe1dd0d02b796f133161750524526ea8f1603e8df4d44b2a37b197f`
- `price_baseline_trades.parquet`: `79ec9b89005bdc0cdfb7a41a9f5e2f825c4057e1406b102dd50ca2206a238c05`
- `robustness_summary.csv`: `0b70f5fbd3848d86c697353bfeab971c8642848b52bc07d39ff895da9194f6d9`
- `trade_metrics.csv`: `0ce92cea3edadb7c417f1d80d46eb2515ddff5f28ac5f8efa870707e43a4f9cc`
- `transaction_cost_sensitivity.csv`: `f3cae0ead97350a49fd1d4ba32c887def2af9c990e934c9b970db1891d87859b`
- `winner_preservation.csv`: `deb6ea48d24bd6255c18506c80d60da915fc7e134e703d56bdf9c9880bad21d1`

## Hard gates

`CANDIDATE_UNIVERSE_FROZEN: YES`
`PRICE_BASELINE_PIT_SAFE: YES`
`PRICE_BASELINE_PROFITABLE_AFTER_COSTS: NO`
`CHIP_STATE_HAS_INCREMENTAL_PNL_INFORMATION: MIXED`
`CANONICAL_BASE_HAS_ECONOMIC_VALUE: MIXED`
`ENSEMBLE_AMBIGUITY_HAS_ECONOMIC_VALUE: MIXED`
`MASS_PROMINENCE_ENTRY_LEVEL_HAS_ECONOMIC_VALUE: NO`
`MASS_PROMINENCE_DETERIORATION_HAS_ECONOMIC_VALUE: MIXED`
`CHIP_CONFIRMATION_IMPROVES_PNL: YES`
`CHIP_SIZING_IMPROVES_RISK_ADJUSTED_RETURN: YES`
`CHIP_HEALTH_IMPROVES_WINNER_HOLDING: MIXED`
`CHIP_DETERIORATION_REDUCES_DOWNSIDE: MIXED`
`CHIP_OVERLAY_IMPROVES_HOLDOUT_NET_RETURN: YES`
`CHIP_OVERLAY_IMPROVES_HOLDOUT_MAX_DRAWDOWN: YES`
`CHIP_OVERLAY_IMPROVES_HOLDOUT_PROFIT_FACTOR: YES`
`CHIP_OVERLAY_ECONOMICALLY_MEANINGFUL: MIXED`
`CHIP_COMPLEXITY_JUSTIFIED_BY_PNL: MIXED`
`SAFE_TO_DESIGN_PNL_ORIENTED_SWING_STRATEGY: YES`
`SAFE_TO_IMPLEMENT_NEW_PRODUCTION_STRATEGY: NO`
`SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941: NO`
