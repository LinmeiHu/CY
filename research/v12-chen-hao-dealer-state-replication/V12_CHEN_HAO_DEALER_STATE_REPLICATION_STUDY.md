# V12 Chen Hao Dealer-State Replication Study

## Outcome

This is a research-only replication on the immutable 500-symbol V12 V3 chip cohort. Chen Hao's framework is classified **PARTIALLY_VALIDATED**. The full-distribution dealer-state inference gate is **MIXED** and the dedicated trading-study gate is **NO**.

The word “dealer” below names a source hypothesis, not an observed investor. The measured objects are `INFERRED_LOCKED_LOW_COST_INVENTORY`, inferred control mass, inferred holder profit, and base retention/migration. No investor identity or disclosed holder position is present in the chip artifact.

No production strategy, V3 semantics, seller model, frozen universe, or input artifact was changed. No 3,941-symbol build was started. Signals at checkpoint T use only states available at T, and every outcome begins at T+1.

## Frozen provenance and design

- Source commit: `d52f9c97970b37f48525bc7320d337b6fb932a4f`
- Frozen root manifest SHA-256: `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a`
- Freeze-lock SHA-256: `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9`
- Universe: 500 symbols; seller models: UNIFORM, DISPOSITION, ACTIVE_STICKY
- Research-valid model/ensemble checkpoint rows: 25,152; crossing events: 2,862
- Chronology: discovery through 2020-04-30; validation 2020-05-01 to 2020-08-31; untouched holdout from 2020-09-01.
- Horizons: 5, 10, 20, 40, 60, 120 trading sessions.
- Controls: deterministic nearest observations within seller model, chronology split, and market regime, matched on prior 60-session return, 20-session volatility, 252-session price position, market return, and calendar distance.
- Market taxonomy: PIT-safe equal-weight return and breadth of the same frozen cohort; unconditional and conditional results are both retained.

## Source-faithful reproducibility boundary

The method catalogue contains 4 exactly reproducible, 12 approximately reproducible, and 1 unavailable translations. Definitions were checked against the accessible [book text](https://xqdoc.imedao.com/169d51450804c03f3fed727b.pdf) and its [chapter transcription](https://blog.sina.com.cn/s/blog_9e33391b0101kzmu.html).

Exact daily `CYQKLEN > 18` is **UNAVAILABLE**. It requires the authoritative full distribution immediately before each day's OHLC, while the governed frozen bundle contains model-specific full distributions at checkpoints. The study does not replay or substitute an unrelated daily metric. `low_turnover_crossing_results.csv` instead reports a clearly labeled static prior-checkpoint crossing test.

Checkpoint identity holding-day cells make age deterministic, but ages are capped at the production artifact's 180-day bucket. Cumulative turnover since first becoming highly profitable is an explicitly approximate surviving-inventory reconstruction. Retention and migration themselves are exact checkpoint distribution comparisons after authoritative corporate-action transforms; ratios and migration losses are never clipped or normalized.

## Direct answers

1. **Does substantial profit with the low-cost inventory still locked predict further medium-term upside?** MIXED.
2. **Does predictive value depend on the inferred holder's profit?** MIXED for low/moderate profit; extreme-profit risk is MIXED.
3. **Does upward migration predict weaker continuation or greater downside?** MIXED.
4. **Does 90比3 validate out of sample?** MIXED.
5. **Does 90比3 work only at low/moderate price positions?** NO.
6. **Does low-turnover crossing validate the no-relief-selling interpretation?** YES (static prior-checkpoint replication, not exact CYQKLEN).
7. **Does the down-shift method identify economically meaningful inventory?** MIXED.
8. **Does the consolidation method identify meaningful retained inventory?** MIXED.
9. **Are wounded-dealer states associated with stronger rebounds?** MIXED.
10. **Are full-distribution double-peak states useful?** MIXED.
11. **Does market regime materially condition results?** YES.
12. **Does seller-model agreement improve validity?** MIXED.
13. **Are effects stronger at 40/60/120 sessions than 5/10?** MIXED.
14. **Does the full distribution permit useful inference despite mixed canonical-peak evidence?** MIXED.
15. **Is the framework reproducible enough for a dedicated trading study?** NO.

## Key evidence

- The ensemble locked-versus-migrated matched return excess at 60 sessions was +1.62% in validation and +6.05% in holdout. That favorable ensemble result is not promoted to YES because ACTIVE_STICKY and UNIFORM had negative 40/60-session holdout differences; seller-model robustness is therefore MIXED.
- Migration-versus-retention at 60 sessions was -3.20% in validation but +2.02% in holdout, directly producing the MIXED distribution-risk conclusion.
- Low-turnover release of at least 18% of static trapped inventory exceeded the high-turnover crossing control by +2.66% in validation and +6.02% in holdout at 60 sessions, with sufficient cross-seller support. This validates only the checkpoint-based crossing translation, not exact CYQKLEN.
- 90比3 showed +3.20% validation and +7.63% holdout matched excess at 60 sessions, but horizon and price-position stratification were not jointly robust, so its overall gate remains MIXED.
- Strict source-faithful rare states were underpowered: consolidation had 1 high-retention out-of-sample event at most, wounded-control had 4, and strong retained lower-peak/rapid-drawdown had 27. Their scorecard classifications remain descriptive or partial rather than validated.

## Dealer-method economic scorecard

Matched effects below are future-return differences at 60 sessions (target minus the named control); all horizons and outcome families remain in the CSV outputs.

| source_method                                         | reproducibility            |   out_of_sample_event_count |   validation_effect_60 |   holdout_effect_60 | classification      |
|:------------------------------------------------------|:---------------------------|----------------------------:|-----------------------:|--------------------:|:--------------------|
| 牛长熊短                                              | APPROXIMATELY_REPRODUCIBLE |                          68 |             -0.0098726 |         -0.0400864  | DESCRIPTIVE_ONLY    |
| 横盘法                                                | APPROXIMATELY_REPRODUCIBLE |                           1 |              0.237867  |        nan          | DESCRIPTIVE_ONLY    |
| 成本低位锁定 while price rises                        | EXACTLY_REPRODUCIBLE       |                         154 |              0.016206  |          0.0605458  | PARTIALLY_VALIDATED |
| 博弈K线低位无量长阳                                   | UNAVAILABLE                |                           0 |            nan         |        nan          | UNAVAILABLE         |
| 双峰填谷                                              | APPROXIMATELY_REPRODUCIBLE |                         197 |              0.0352463 |          0.00594117 | DESCRIPTIVE_ONLY    |
| 下移法                                                | APPROXIMATELY_REPRODUCIBLE |                          44 |              0.0446807 |         -0.188307   | PARTIALLY_VALIDATED |
| 高位密集 / distribution warning                       | APPROXIMATELY_REPRODUCIBLE |                         145 |             -0.178672  |          0.0157582  | DESCRIPTIVE_ONLY    |
| 大双峰 / 双峰峡谷                                     | APPROXIMATELY_REPRODUCIBLE |                          27 |            nan         |         -0.220079   | DESCRIPTIVE_ONLY    |
| low-cost inventory retention after substantial profit | EXACTLY_REPRODUCIBLE       |                         154 |              0.016206  |          0.0605458  | PARTIALLY_VALIDATED |
| low-cost inventory migration / disappearance          | EXACTLY_REPRODUCIBLE       |                         106 |             -0.0319774 |          0.0202037  | PARTIALLY_VALIDATED |
| 低位密集                                              | APPROXIMATELY_REPRODUCIBLE |                         221 |              0.0636774 |         -0.0289493  | DESCRIPTIVE_ONLY    |
| 低位锁定                                              | APPROXIMATELY_REPRODUCIBLE |                           8 |             -0.0457673 |         -0.0981111  | DESCRIPTIVE_ONLY    |
| 筹码密集区无量上穿                                    | APPROXIMATELY_REPRODUCIBLE |                         147 |              0.02659   |          0.0601524  | VALIDATED           |
| 90比3                                                 | EXACTLY_REPRODUCIBLE       |                          87 |              0.0320255 |          0.0762689  | PARTIALLY_VALIDATED |
| 挖坑后坑沿强势横盘                                    | APPROXIMATELY_REPRODUCIBLE |                          39 |              0.0129122 |         -0.0390334  | DESCRIPTIVE_ONLY    |
| 次低位窄幅横盘                                        | APPROXIMATELY_REPRODUCIBLE |                         148 |              0.0859304 |         -0.0156694  | DESCRIPTIVE_ONLY    |
| 受伤庄股                                              | APPROXIMATELY_REPRODUCIBLE |                           4 |            nan         |          0.398848   | DESCRIPTIVE_ONLY    |

## Interpretation discipline and limitations

The sample is the frozen engineering cohort concentrated in Shenzhen symbols during 2020, not a probability sample of the A-share market. Monthly full-distribution cadence limits daily source replication and makes some pattern translations approximate. Holding ages saturate at 180 sessions. Matching reduces observable trend/position/volatility/regime differences but cannot identify an unobserved investor or establish causality. Multiple seller models remain hypotheses; no best seller model is selected.

Canonical peak validity is not an eligibility gate anywhere in this study. Full distributions are primary; tracked modes are used only where the source method itself requires a dense region or two-peak structure.

## Hard gates

`CHEN_HAO_CORE_METHODS_REPRODUCED_FAITHFULLY: PARTIAL`
`LOCKED_PROFITABLE_INVENTORY_HAS_MEDIUM_TERM_SIGNAL: MIXED`
`HIGH_CONTROL_LOW_MODERATE_PROFIT_HAS_SIGNAL: MIXED`
`HIGH_CONTROL_EXTREME_PROFIT_IS_RISKIER: MIXED`
`LOW_COST_BASE_RETENTION_PREDICTS_CONTINUATION: MIXED`
`LOW_COST_BASE_MIGRATION_PREDICTS_DISTRIBUTION_RISK: MIXED`
`DOWNSHIFT_METHOD_VALIDATES: MIXED`
`CONSOLIDATION_METHOD_VALIDATES: MIXED`
`NINETY_VS_THREE_VALIDATES: MIXED`
`LOW_TURNOVER_TRAPPED_CHIP_CROSSING_VALIDATES: YES`
`WOUNDED_DEALER_HYPOTHESIS_VALIDATES: MIXED`
`DOUBLE_PEAK_DEALER_STRUCTURE_VALIDATES: MIXED`
`MARKET_REGIME_MATERIALLY_CONDITIONS_DEALER_SIGNAL: YES`
`SELLER_MODEL_AGREEMENT_IMPROVES_DEALER_STATE_VALIDITY: MIXED`
`DEALER_SIGNAL_STRONGER_AT_MEDIUM_TERM_HORIZONS: MIXED`
`FULL_DISTRIBUTION_SUPPORTS_DEALER_STATE_INFERENCE: MIXED`
`CHEN_HAO_DEALER_FRAMEWORK_OVERALL: PARTIALLY_VALIDATED`
`SAFE_TO_DESIGN_DEALER_STATE_TRADING_STUDY: NO`
`SAFE_TO_CHANGE_PRODUCTION_CHIP_SEMANTICS: NO`
`SAFE_TO_IMPLEMENT_PRODUCTION_DEALER_STRATEGY: NO`
`SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941: NO`
