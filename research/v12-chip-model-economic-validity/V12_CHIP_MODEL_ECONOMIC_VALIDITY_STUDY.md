# V12 Chip Model Economic Validity Study

## Outcome

This is a research-only economic-validity result on the frozen 500-symbol V3 cohort. The evidence classification is **MIXED**. No production strategy code, V3 temporal semantics, seller-model semantics, frozen chip artifact, or authoritative lifecycle ledger was modified. No full-market build was started.

The study does not use setup pass/fail, entries, exits, P&L, winner labels, profitable trades, or strategy-derived feature selection. Every primary level is frozen at an immutable opening/month-end checkpoint; all reaction windows start at T+1. Corporate actions transform the fixed level with the authoritative `(C-D)/R` coordinate before later price comparisons.

## Frozen provenance and population

- Baseline/source commit: `845b90bb9d1691bb7f8914b0307aee9180a75a78`
- Frozen root manifest SHA-256: `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a`
- Freeze-lock SHA-256: `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9`
- Build source commit: `ea01eedf02029c2a3ac9a4828f249101bed44fc9`
- Peak definition: `canonical-chip-peak-v2`; temporal tracker: `temporal-chip-peak-v3`
- Seller models: `UNIFORM`, `DISPOSITION`, `ACTIVE_STICKY`; ensemble is reported separately
- Universe: 500 symbols; exchanges — SZ: 500
- Symbol prefixes — 000: 455, 001: 6, 002: 39
- Industry availability: 500/500; largest groups — UNKNOWN: 43, 房地产开发: 30, 电力: 29, 化学制药: 20, 汽车零部件: 16, 一般零售: 12, 环境治理: 11, 化学原料: 10, 工业金属: 10, 炼化及贸易: 10, 光学光电子: 9, 农化制品: 9, 中药Ⅱ: 8, 旅游及景区: 8, 综合Ⅱ: 8
- Feature coverage: 2020-01-02 through 2020-12-31; 121,251 daily rows
- Checkpoint/model snapshots analyzed: 25,204; eligible tracked levels: 72,367; first-touch observations: 88,154; placebo definitions: 10,028
- Checkpoint model/ensemble state-level `hard_valid` flags: 193; frozen daily-fact `hard_valid` rows: 0; research-valid checkpoint/model snapshots: 25,204. `hard_valid` is not weakened: the study uses the separately governed B-grade research-valid contract and preserves unknown-cost mass explicitly.
- Sampling limitation: Frozen engineering research cohort, not a probability sample of the A-share market; coverage is concentrated in the manifest's prefixes/exchanges and cannot establish full-market, delisting, or later-listing generality.

## Method fixed before aggregate outcomes

The exact operational definitions and economic directions are in `preregistered_protocol.json`. Discovery ends 2020-04-30, validation covers 2020-05-01 through 2020-08-31, and holdout begins 2020-09-01. Discovery determines only quintile/shape bins. Bands never move using future observations except the required authoritative corporate-action coordinate transform.

Matched placebos keep symbol, checkpoint, side, recent volatility/trend, relative width, calendar regime, and a nearby fixed distance. From four preregistered distance shifts, the lowest modeled-mass non-overlapping band is retained only when its mass is no more than half the real band's. Price-only controls use the prior 20-session swing low/high. Old-base and ambiguity comparisons use deterministic same-symbol nearest controls on distance/volatility/trend/calendar geometry. Repeated touches remain clustered by deterministic `level_id`; checkpoint-state uncertainty is clustered by symbol.

The full-distribution descriptors are intentionally small and interpretable: weighted mean/median, p10/p90, width, known-cost fraction, mass below/above and within 5% of price, bucket HHI, normalized entropy, tracked mode count, and top-mode separation. There is no black-box feature search and no threshold optimization on validation or holdout.

Corporate-action sanity reports 2,107 metric comparisons and 2 review-threshold anomalies. Exact daily full-distribution pre/post comparison is `UNAVAILABLE_WITHOUT_REPLAY`; the study does not invent it or rebuild the frozen root.

## Required questions

1. **Do lower concentrations behave like support?** MIXED.
2. **Do upper concentrations behave like resistance?** MIXED.
3. **Do chip levels outperform matched arbitrary levels?** MIXED.
4. **Do chip levels add beyond prior price support/resistance?** MIXED.
5. **Is there a mass/prominence dose response?** MIXED.
6. **Does repeated touching show inventory-depletion decay?** MIXED.
7. **Does cost migration map to future structure?** YES.
8. **Does old-base destruction reduce support?** MIXED.
9. **Does a new rolling base acquire support value?** MIXED.
10. **Best seller model?** NONE.
11. **Does ensemble consensus improve validity?** YES.
12. **Does ambiguity have interpretable economic meaning?** NO.
13. **Is the full distribution more informative than the canonical peak?** YES.
14. **Are multi-peak/broad states meaningful?** NO.
15. **Is there a validated swing-horizon effect?** MIXED; all 1/3/5/10/20/40-session results remain visible in `horizon_map.csv`.
16. **Does chip modeling add beyond ordinary price/volume structure?** Price-only: MIXED; authoritative non-chip volume-at-price benchmark: UNAVAILABLE.
17. **Valid enough to continue strategy research?** MIXED; this does not authorize a production strategy.
18. **Is seller-model redesign study warranted?** YES.
19. **Is peak compression a likely information-loss source?** YES.

## Seller-model tournament

The machine-readable `seller_model_scorecard.csv` preserves every model/test/period result rather than collapsing heterogeneous metrics into an optimized score. The best-model gate is `NONE` and the seller-model-difference gate is `YES`. Any `MIXED` result means period, model, representation, outcome, or power disagreed; it is not silently promoted.

## Falsification and limitations

The falsification table includes matched low-mass non-chip levels, an explicitly non-primary future-checkpoint time shift, weak-versus-strong peaks, and model-disagreement states. A separate authoritative PIT-safe non-chip volume-at-price artifact was not found in the frozen governed inputs, so that benchmark is reported `UNAVAILABLE` rather than constructed ad hoc.

Monthly checkpoints make full seller-model distributions authoritative and immutable but reduce event-definition cadence. The daily canonical fact supports action sanity and daily future outcomes; exact daily model-specific full distributions would require governed replay and are outside this no-rebuild study. Results therefore establish, weaken, or fail economic interpretations only for this frozen cohort and cadence.

## Hard gates

`SUPPORT_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE: MIXED`
`RESISTANCE_HYPOTHESIS_VALIDATES_OUT_OF_SAMPLE: MIXED`
`CHIP_LEVELS_OUTPERFORM_MATCHED_PLACEBOS: MIXED`
`CHIP_ADDS_VALUE_BEYOND_PRICE_ONLY_LEVELS: MIXED`
`PEAK_STRENGTH_SHOWS_ECONOMIC_DOSE_RESPONSE: MIXED`
`REPEATED_TOUCH_DECAY_SUPPORTS_INVENTORY_INTERPRETATION: MIXED`
`COST_MIGRATION_HAS_ECONOMIC_VALIDITY: YES`
`OLD_BASE_DESTRUCTION_REDUCES_FUTURE_SUPPORT: MIXED`
`NEW_ROLLING_BASE_ACQUIRES_SUPPORT_VALUE: MIXED`
`BEST_VALIDATED_SELLER_MODEL: NONE`
`SELLER_MODELS_DIFFER_ECONOMICALLY: YES`
`ENSEMBLE_CONSENSUS_IMPROVES_VALIDITY: YES`
`ENSEMBLE_AMBIGUITY_HAS_INTERPRETABLE_ECONOMIC_MEANING: NO`
`FULL_DISTRIBUTION_OUTPERFORMS_CANONICAL_PEAK: YES`
`MULTI_PEAK_STRUCTURE_HAS_ECONOMIC_INFORMATION: NO`
`CHIP_INFORMATION_HAS_VALIDATED_SWING_HORIZON_EFFECT: MIXED`
`CANONICAL_PEAK_ECONOMIC_CLASSIFICATION: PARTIALLY_VALIDATED`
`FULL_DISTRIBUTION_ECONOMIC_CLASSIFICATION: PARTIALLY_VALIDATED`
`CHIP_MODEL_ECONOMIC_VALIDITY_OVERALL: MIXED`
`SELLER_MODEL_REDESIGN_STUDY_JUSTIFIED: YES`
`CANONICAL_PEAK_COMPRESSION_REDESIGN_STUDY_JUSTIFIED: YES`
`SAFE_TO_CONTINUE_USING_V3_CHIP_FOR_RESEARCH: MIXED`
`SAFE_TO_CHANGE_PRODUCTION_CHIP_SEMANTICS: NO`
`SAFE_TO_DESIGN_PRODUCTION_STRATEGY: NO`
`SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941: NO`
