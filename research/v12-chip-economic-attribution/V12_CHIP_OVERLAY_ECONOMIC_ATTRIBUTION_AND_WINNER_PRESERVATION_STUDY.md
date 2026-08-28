# V12 Chip Overlay Economic Attribution and Winner Preservation Study

## Executive answer

The controlled P0 candidate universe and trades were consumed unchanged from `0601a6e82e`. The accounting contradiction is fully reconciled, and the 92-to-6 winner collapse is localized. P6's headline result is not evidence of strong completed-trade economics: its equal-trade PF remains 0.680. The dominant major-winner loss mechanism is `FILTERING`, with the largest single collapse at `P2_CANONICAL_PERSISTENCE`.

The pre-registered soft family was not chosen on validation or holdout. `COMBINED_S1_D3` won the discovery-only preservation-first rule and is reported canonically as `BEST_PREREGISTERED_SOFT_COMBINED`.

No production strategy code or V3 semantics changed. No chip or candidate artifact was rewritten. No 3,941-symbol build was started.

## 1. Exact P6 accounting reconciliation

Holdout start equity was 1.183669 and end equity was 1.259371, a net change of 0.075702 and return of 6.40%. The exact identity is:

`end equity - start equity = realized net P&L + terminal unrealized net P&L`

`0.075701938 = -0.053484189 + 0.129186127`

Residual: `-2.498e-16`. Gross realized P&L is -0.032634, gross terminal P&L is 0.129944, and period transaction costs are 0.021608. P6 ends with 7 open positions, 83.24% average exposure, turnover 14.356, and 0.205470 cash.

Removing terminal unrealized P&L produces -4.52%. Therefore terminal mark-to-market dependence is `YES` and this sign test is prominent by construction.

- Unresolved/open terminal positions materially determine the sign: `YES`.
- Top-three positive position contribution share is 61.38%; concentrated-position dependence is `YES` under a 50% descriptive threshold.
- Equal-size P6 returns 2.91%. The positive sign does not depend on sizing, but magnitude dependence is `YES` under a two-point/sign-change rule.
- Low exposure does not manufacture profit; it dilutes the invested sleeve. Material low-exposure dependence is `NO`.
- Mark-to-market dependence is `YES`.

## 2. Baseline-to-P6 winner survival waterfall

| stage                    |   baseline_trades_remaining |   baseline_winners_remaining |   baseline_top_decile_winners_remaining |   baseline_losers_removed |   baseline_large_losers_removed | total_top_decile_mfe_retained_fraction   | effective_realized_return_sum_retained   |
|:-------------------------|----------------------------:|-----------------------------:|----------------------------------------:|--------------------------:|--------------------------------:|:-----------------------------------------|:-----------------------------------------|
| P0_PRICE_ONLY            |                         915 |                          219 |                                      92 |                         0 |                               0 | 100.00%                                  | -1262.08%                                |
| P1_TEMPORAL_CONFIRMATION |                         732 |                          175 |                                      71 |                       139 |                              20 | 76.52%                                   | -965.67%                                 |
| P2_CANONICAL_PERSISTENCE |                         233 |                           47 |                                      16 |                       510 |                              51 | 19.43%                                   | -366.08%                                 |
| P3_MASS_PROMINENCE       |                          90 |                           19 |                                       6 |                       625 |                              57 | 7.65%                                    | -115.63%                                 |
| P4_CHIP_SIZING           |                          90 |                           19 |                                       6 |                       625 |                              57 | 9.82%                                    | -148.42%                                 |
| P5_HEALTHY_HOLDING       |                          90 |                           19 |                                       6 |                       625 |                              57 | 9.82%                                    | -118.39%                                 |
| P6_DETERIORATION_DERISK  |                          90 |                           19 |                                       6 |                       625 |                              57 | 9.82%                                    | -109.87%                                 |

The largest single top-decile loss is `P2_CANONICAL_PERSISTENCE` with 55 winners removed. Exact per-trade reasons and PIT-safe chip paths are in `top_winner_intervention_audit.parquet`; the compact one-row-per-winner form is `top_winner_intervention_summary.csv`.

## 3. Filtering, sizing, and truncation

For the 92 holdout top-decile winners, the P6 economic-loss decomposition is:

- Filtered before entry: 14.098 cumulative equal-trade return units
- Reduced through sizing: 0.000 cumulative equal-trade return units
- Truncated after entry: 0.000 cumulative equal-trade return units

These are sequential and non-overlapping: filtering first, then sizing on accepted trades, then the sized difference between baseline and chip-managed exits.

## 4. Stage economic attribution

| to_stage                 | incremental_net_pnl   | drawdown_reduction   |   large_loss_count_reduction | top_decile_winner_pnl_sacrificed   | incremental_top_decile_mfe_lost   | exposure_impact   | economic_classification   |
|:-------------------------|:----------------------|:---------------------|-----------------------------:|:-----------------------------------|:----------------------------------|:------------------|:--------------------------|
| P1_TEMPORAL_CONFIRMATION | 13.09%                | 6.74%                |                           20 | 345.59%                            | 548.23%                           | -0.98%            | VALUE_CREATING            |
| P2_CANONICAL_PERSISTENCE | 7.01%                 | 2.80%                |                           31 | 886.20%                            | 1333.09%                          | -4.48%            | WINNER_DESTRUCTIVE        |
| P3_MASS_PROMINENCE       | -4.41%                | -2.93%               |                            6 | 177.99%                            | 275.11%                           | -10.55%           | WINNER_DESTRUCTIVE        |
| P4_CHIP_SIZING           | 3.27%                 | -0.47%               |                            0 | -30.66%                            | -50.64%                           | 2.13%             | VALUE_CREATING            |
| P5_HEALTHY_HOLDING       | 1.57%                 | -0.15%               |                            0 | 0.00%                              | 0.00%                             | 0.56%             | VALUE_CREATING            |
| P6_DETERIORATION_DERISK  | 1.89%                 | 0.00%                |                            1 | 0.00%                              | 0.00%                             | -0.26%            | VALUE_CREATING            |

Classifications require validation/holdout direction, with a separate winner-destruction override when a step loses at least 25% of the prior top-decile MFE.

## 5. Source of isolated confirmation value

| split      | group_value   |   trades | mean_baseline_net_return   | mean_mae   | mean_mfe   | large_loss_probability   | large_winner_probability   |   profit_factor |
|:-----------|:--------------|---------:|:---------------------------|:-----------|:-----------|:-------------------------|:---------------------------|----------------:|
| validation | REMOVED       |      286 | 0.98%                      | -4.94%     | 12.09%     | 13.64%                   | 15.38%                     |        1.28634  |
| validation | RETAINED      |      731 | 1.58%                      | -3.93%     | 10.65%     | 6.98%                    | 14.77%                     |        1.60325  |
| holdout    | REMOVED       |      183 | -1.62%                     | -4.91%     | 7.19%      | 10.93%                   | 8.20%                      |        0.580646 |
| holdout    | RETAINED      |      732 | -1.32%                     | -4.22%     | 5.83%      | 5.46%                    | 7.10%                      |        0.60988  |

P1 accepts only exact `VALID_CANONICAL_BASE` and `ENSEMBLE_AMBIGUOUS` states. It rejects observed topology-transition states without inventing a canonical base. Validation and holdout removed sets have worse downside incidence/MAE than retained sets, but rejected `MERGE` and other topology states also contain major winners. Thus the useful signal is downside enrichment, not clean direction prediction.

State-level details, base age/persistence, mass, prominence, ambiguity, MAE, MFE, and tail probabilities are in `confirmation_removed_trade_analysis.csv`.

## 6. Required soft/deterioration comparison

| variant                                    | net_return   |   profit_factor |   weighted_profit_factor | max_drawdown   |   sharpe | exposure   |   top_decile_winners_retained |   top_decile_winners | top_decile_mfe_retained_fraction   |   large_losers_removed_or_reduced |
|:-------------------------------------------|:-------------|----------------:|-------------------------:|:---------------|---------:|:-----------|------------------------------:|---------------------:|:-----------------------------------|----------------------------------:|
| P0_PRICE_ONLY                              | -16.03%      |        0.603387 |                 0.603387 | -20.16%        | -2.6401  | 96.81%     |                            92 |                   92 | 100.00%                            |                                 0 |
| I_CONFIRMATION_ONLY                        | -2.94%       |        0.60988  |                 0.60988  | -13.41%        | -0.40316 | 95.84%     |                            71 |                   92 | 76.52%                             |                                20 |
| P6_DETERIORATION_DERISK                    | 6.40%        |        0.680431 |                 0.680431 | -14.16%        |  1.07662 | 83.24%     |                             6 |                   92 | 9.82%                              |                                58 |
| SOFT_S1_MILD                               | -12.33%      |        0.603387 |                 0.593654 | -15.52%        | -2.56628 | 77.33%     |                            92 |                   92 | 74.70%                             |                                46 |
| SOFT_S2_CONSERVATIVE                       | -10.25%      |        0.603387 |                 0.575999 | -12.51%        | -2.63869 | 62.01%     |                            92 |                   92 | 55.28%                             |                                46 |
| DETERIORATION_D1_BLOCK_ADDS                | -16.03%      |        0.603387 |                 0.603387 | -20.16%        | -2.6401  | 96.81%     |                            92 |                   92 | 100.00%                            |                                 0 |
| DETERIORATION_D2_REDUCE_25_RETAIN_CORE     | -15.66%      |        0.602982 |                 0.602982 | -19.83%        | -2.56938 | 96.58%     |                            92 |                   92 | 100.00%                            |                                 1 |
| DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50 | -15.60%      |        0.601864 |                 0.601864 | -19.77%        | -2.55979 | 96.56%     |                            92 |                   92 | 100.00%                            |                                 1 |
| BEST_PREREGISTERED_SOFT_COMBINED           | -12.20%      |        0.601864 |                 0.59146  | -15.40%        | -2.53765 | 77.20%     |                            92 |                   92 | 74.70%                             |                                47 |

S1 is `1.00/0.75/0.50` and S2 is `1.00/0.50/0.25` for exact favorable/uncertain/weak entry states. D1 is a deliberate no-op because adding is forbidden by the carrier. D2 sells 25% on validated same-track mass-and-prominence deterioration. D3 sells 50% only with contemporaneous price confirmation. Every action fills no earlier than the next legal open and retains a core.

## 7. Deterioration and winner-holding audit

| warning_type                | split      |   warnings |   median_lead_sessions |   mean_lead_sessions |   large_loss_probability |   false_warning_rate_profitable_trade |   top_decile_winner_warning_rate |   mean_mae |   mean_mfe |   mean_mfe_remaining_after_warning |
|:----------------------------|:-----------|-----------:|-----------------------:|---------------------:|-------------------------:|--------------------------------------:|---------------------------------:|-----------:|-----------:|-----------------------------------:|
| D2_VALIDATED_DETERIORATION  | holdout    |          8 |                    5   |             4.875    |                    0.125 |                              0.125    |                        0.125     | -0.0618704 |   0.10908  |                         0.0343378  |
| D2_VALIDATED_DETERIORATION  | validation |         22 |                    3   |             3.63636  |                    0     |                              0.818182 |                        0.272727  | -0.0331099 |   0.267219 |                         0.0910169  |
| D3_DETERIORATION_PLUS_PRICE | holdout    |          8 |                    4.5 |             4.5      |                    0.125 |                              0.125    |                        0.125     | -0.0618704 |   0.10908  |                         0.0343378  |
| D3_DETERIORATION_PLUS_PRICE | validation |         12 |                    1   |             0.916667 |                    0     |                              0.75     |                        0.0833333 | -0.0361576 |   0.130529 |                         0.00500408 |

False-warning rate is defined transparently as the fraction of warnings on ultimately profitable baseline trades. MFE remaining is diagnostic and never used by a live rule. The full aligned winner/loser trajectories are in `winner_loser_chip_trajectories.parquet`.

## 8. Topology-state conditional economics

| event              |   event_trades | delta_mean_net_return   | delta_large_loss_probability   | event_large_winner_probability   | classification        |
|:-------------------|---------------:|:------------------------|:-------------------------------|:---------------------------------|:----------------------|
| SPLIT              |            268 | 3.23%                   | 5.50%                          | 14.55%                           | REGIME_DEPENDENT      |
| MERGE              |            331 | 3.24%                   | 4.40%                          | 13.29%                           | REGIME_DEPENDENT      |
| LOST               |            563 | 3.75%                   | 0.96%                          | 11.01%                           | REGIME_DEPENDENT      |
| REBINDING          |             19 | 7.75%                   | -6.70%                         | 26.32%                           | INSUFFICIENT_EVIDENCE |
| ENSEMBLE_AMBIGUITY |            680 | 1.39%                   | -0.34%                         | 8.38%                            | REGIME_DEPENDENT      |

Topology is not encoded automatically as bearish. Classification requires replicated validation/holdout return and large-loss direction; otherwise it is regime-dependent or insufficient.

## 9. Cross-baseline consistency

| feature_or_overlay   | consistency_classification   |
|:---------------------|:-----------------------------|
| D3_DERISK            | ROBUST_ACROSS_BASELINES      |
| HARD_CONFIRMATION    | BASELINE_SPECIFIC            |
| SOFT_S1              | ROBUST_ACROSS_BASELINES      |
| SOFT_S1_PLUS_D3      | ROBUST_ACROSS_BASELINES      |

The same exact state mapping and deterioration thresholds were applied to `T1_CLOSE_STRENGTH`, `T2_RECLAIM_PRIOR_3_HIGH`, and `T3_TREND_RESUMPTION`. No carrier or chip parameter was selected on holdout.

## 10. Pareto frontier and Profit Factor reconciliation

| variant                                    |   net_return |   max_drawdown |   top_decile_winners_retained |   top_decile_winners |   top_decile_mfe_retained_fraction |   profit_factor |   weighted_profit_factor | pareto_dominated   | dominated_by        | pareto_frontier   |
|:-------------------------------------------|-------------:|---------------:|------------------------------:|---------------------:|-----------------------------------:|----------------:|-------------------------:|:-------------------|:--------------------|:------------------|
| P0_PRICE_ONLY                              |   -0.16028   |      -0.20155  |                            92 |                   92 |                          1         |        0.603387 |                 0.603387 | False              |                     | True              |
| I_CONFIRMATION_ONLY                        |   -0.0293911 |      -0.134128 |                            71 |                   92 |                          0.765211  |        0.60988  |                 0.60988  | False              |                     | True              |
| P6_DETERIORATION_DERISK                    |    0.0639553 |      -0.141592 |                             6 |                   92 |                          0.0981664 |        0.680431 |                 0.680431 | False              |                     | True              |
| SOFT_S1_MILD                               |   -0.123338  |      -0.155239 |                            92 |                   92 |                          0.747041  |        0.603387 |                 0.593654 | True               | I_CONFIRMATION_ONLY | False             |
| SOFT_S2_CONSERVATIVE                       |   -0.102467  |      -0.125062 |                            92 |                   92 |                          0.55278   |        0.603387 |                 0.575999 | False              |                     | True              |
| DETERIORATION_D1_BLOCK_ADDS                |   -0.16028   |      -0.20155  |                            92 |                   92 |                          1         |        0.603387 |                 0.603387 | False              |                     | True              |
| DETERIORATION_D2_REDUCE_25_RETAIN_CORE     |   -0.15659   |      -0.198261 |                            92 |                   92 |                          1         |        0.602982 |                 0.602982 | False              |                     | True              |
| DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50 |   -0.156018  |      -0.197716 |                            92 |                   92 |                          1         |        0.601864 |                 0.601864 | False              |                     | True              |
| BEST_PREREGISTERED_SOFT_COMBINED           |   -0.122016  |      -0.153966 |                            92 |                   92 |                          0.747041  |        0.601864 |                 0.59146  | True               | I_CONFIRMATION_ONLY | False             |

Variants with positive portfolio return but equal-trade PF below one reconcile as follows:

| variant                 | split   | portfolio_net_return   |   completed_equal_trade_profit_factor |   admitted_completed_equal_trade_profit_factor |   realized_period_money_weighted_profit_factor | terminal_unrealized_net_pnl   | sizing_contribution_to_portfolio_return   | reconciliation_explanation                                                                                                           |
|:------------------------|:--------|:-----------------------|--------------------------------------:|-----------------------------------------------:|-----------------------------------------------:|:------------------------------|:------------------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------|
| P6_DETERIORATION_DERISK | holdout | 6.40%                  |                              0.680431 |                                       0.861605 |                                       0.792682 | 12.92%                        | 3.48%                                     | POSITIVE_TERMINAL_MARK_TO_MARKET+CAPACITY_SELECTED_ADMITTED_SUBSET+POSITION_SIZING+TRADE_PF_IS_EQUAL_RETURN_AND_EXCLUDES_OPEN_TRADES |

Equal-trade PF sums unweighted completed-trade returns. Size-weighted PF applies the pre-registered risk allocation. Admitted PF excludes capacity rejections. Period money-weighted PF uses actual portfolio notionals and period-reset bases. Terminal marks remain outside completed-trade PF.

## Required final answers

1. P6 earns 6.40% because period-basis realized net P&L is -0.053484 and terminal unrealized net P&L is 0.129186; their sum reconciles the equity change to a residual of -2.498e-16. Equal-trade PF 0.680 covers 90 completed accepted trades, excludes open trades, ignores capital weights, and includes accepted trades the portfolio could not admit; the portfolio had 53 admitted completed trades and 7 terminal positions.
2. `P2_CANONICAL_PERSISTENCE` destroys the most top-decile winners: 55 at that single step.
3. The primary mechanism is `FILTERING`. Top-winner return loss decomposes to filtering 14.098, sizing 0.000, and premature exit 0.000 in cumulative equal-trade return units.
4. The isolated confirmation effect is the exact P1 exclusion of entry-time `SPLIT`, `MERGE`, and `LOST/TRANSITION` states. The downside asymmetry is concentrated in split/lost observations; merge also contains major winners, so the combined hard gate is not a pure bad-trade oracle.
5. Soft sizing is better for winner preservation (74.70% top-decile MFE versus 9.82% for P6), while downside retention is `YES`.
6. The selected soft combined overlay retains 92/92 top-decile winners and 74.70% of their size-weighted MFE; the acceptable-retention gate is `YES`.
7. Mass/prominence deterioration is better suited to staged de-risking than entry filtering: `MIXED`. D2/D3 preserve a core and never override price stops.
8. Topology events are directly bearish: `MIXED`. The conditional table shows which events are adverse versus regime-dependent normal evolution.
9. Chip risk replicates across more than one carrier: `YES` under the predeclared multi-metric rule.
10. A simple interpretable overlay with positive holdout trade economics and acceptable preservation was found: `NO`.

## Reproducibility and scope

- Prior artifacts verified: 13
- P&L study commit: `0601a6e82e`
- Baseline trades hash: `79ec9b89005bdc0cdfb7a41a9f5e2f825c4057e1406b102dd50ca2206a238c05`
- Candidate universe hash: `3913c3f839c9a5a9f682e47ff256be53a5a8395e371b34df019959692e7dc82a`
- Candidate and baseline hashes were checked again after the run.
- The retrospective winner/loser class appears only in diagnostic outputs and is not consumed by any rule.

Deterministic artifact hashes:

- `confirmation_removed_trade_analysis.csv`: `3e9a379b9b990089c2aa1e159d014695f6c144ea5730cd0e494718d0fa01c998`
- `cross_baseline_chip_consistency.csv`: `8112cbde0429044c9c5bbe90ffb120095295fd42a19ce45676b596a92d025fc0`
- `deterioration_diagnostics.csv`: `0ef1f82a561aab269613aca98621d8c8f7b5a03f28bc73b64e5155fc7f0f93a8`
- `deterioration_response_comparison.csv`: `08ddf35f627e57b70a6d22b8b7301550c5c70412b199b3f3ae4bca26320f4dc7`
- `overlay_stage_attribution.csv`: `ab0eccc159a3c2afbaab0431d07b8533e40fd1a3bfab042cf8cc24aae1d40d32`
- `p6_pnl_reconciliation.csv`: `1563d6b4b2d071ceec20d2d937317088876285eac1bca3b70f2e254d768ca6d3`
- `pareto_frontier.csv`: `0b532d464bdeae9cebfd9fecdbdf599f186944bff1eea83651c030dbb3b2fb22`
- `profit_factor_reconciliation.csv`: `7ee88179573693b543734c94aa5ad7617762abee9fb79057d31229b8ed4b3bba`
- `soft_risk_overlay_comparison.csv`: `8869fbad8d0399f5a4a288f9e7d1b9f96ad2515dc9fe9157c20ae7f3f25a0109`
- `top_winner_intervention_audit.parquet`: `07de9fab0497a2d0be19d1dca3f9f881ee85d540a0c8086999c6150ed8ddd798`
- `top_winner_intervention_summary.csv`: `78f9647ffca88bd5d3b0e465c347df0d906179fce0d1a391bc89a0b373431fa7`
- `topology_state_conditional.csv`: `a59b054cde9ae25f19ef42614cf5093ef1b806b5daffa3a94a7c46363131fe6a`
- `winner_loser_chip_trajectories.parquet`: `b74ef3e1b654e44219c48dfe528fec7d1c181663b90db82632f43f9f0d0925c9`
- `winner_survival_waterfall.csv`: `aa083d4d0f53310e4163bb423ac83c12224218a0442dd54de1cda93759c3dd3a`

## Hard gates

`P6_PORTFOLIO_RETURN_RECONCILED: YES`
`P6_POSITIVE_RETURN_DEPENDS_MATERIALLY_ON_TERMINAL_MARK_TO_MARKET: YES`
`TOP_WINNER_DESTRUCTION_STAGE_IDENTIFIED: YES`
`TOP_WINNER_PRIMARY_LOSS_MECHANISM: FILTERING`
`CONFIRMATION_VALUE_SOURCE_IDENTIFIED: YES`
`CONFIRMATION_VALUE_PRIMARILY_DOWNSIDE_FILTERING: YES`
`HARD_CHIP_FILTERING_OVERSELECTIVE: YES`
`SOFT_CHIP_RISK_SCALING_IMPROVES_WINNER_PRESERVATION: YES`
`SOFT_CHIP_RISK_SCALING_RETAINS_DOWNSIDE_BENEFIT: YES`
`MASS_PROMINENCE_DETERIORATION_BETTER_FOR_DERISKING_THAN_ENTRY_FILTERING: MIXED`
`TOPOLOGY_EVENTS_DIRECTLY_BEARISH: MIXED`
`CHIP_VALUE_ROBUST_ACROSS_PRICE_BASELINES: YES`
`TOP_DECILE_WINNER_RETENTION_ACCEPTABLE: YES`
`POSITIVE_HOLDOUT_TRADE_ECONOMICS_FOUND: NO`
`POSITIVE_HOLDOUT_PORTFOLIO_ECONOMICS_FOUND: YES`
`SIMPLE_INTERPRETABLE_CHIP_OVERLAY_FOUND: NO`
`SAFE_TO_DESIGN_PNL_ORIENTED_SWING_STRATEGY: NO`
`SAFE_TO_IMPLEMENT_NEW_PRODUCTION_STRATEGY: NO`
`SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941: NO`
