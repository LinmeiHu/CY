# ASHARE-TRUE-GAP-LOW-INVENTORY-FILL-PATTERN-DISCOVERY-V1

## Status

`STOPPED_FOR_HUMAN_PATTERN_REVIEW`

This is a pre-2021 in-sample descriptive pattern discovery. It uses no returns, PnL, trade replay, model prediction, or 2021+ observations.

## Broad mother population

The outcome-blind Stage-A screen retained 427 V6 CORE causal-first-return events across 391 symbols. It requires exact 120-session PIT minute history and low raw price occupancy both inside `[L,U]` and in `[L−0.5W,U+0.5W)`, but deliberately does not pre-gate long decline, depth, prior near-touch, or approach shape.

|Population|N|5D U fill|10D U fill|20D U fill|40D U fill|
|---|---:|---:|---:|---:|---:|
|Mother|427|76.35%|83.14%|88.06%|89.70%|
|Simple conditions|119|86.55%|92.44%|97.48%|97.48%|

## Descriptive simple conditions

1. `post_gap_freeze_corridor_float_turnover <= 0.00127097` (Q50; N=214, pooled 20D fill=93.46%, pooled lift=+5.40%, median annual lift=+6.76%).
2. `higher_low_share_10d >= 0.666667` (Q50; N=119, pooled 20D fill=97.48%, pooled lift=+9.42%, median annual lift=+11.11%).

These conditions are discovered and evaluated on the same 2014–2020 observations. They are a compact description of this sample, not evidence of prediction or a strategy.

The condition selector prioritises the number of calendar years with positive uplift before effect size. This prevents a large one-year partition from outranking a smaller but chronologically broader descriptive difference.

## Calendar-year view

|Year|Mother N|Mother 20D|Rule N|Rule 20D|
|---:|---:|---:|---:|---:|
|2014|8|87.50%|3|100.00%|
|2015|57|92.98%|27|96.30%|
|2016|18|88.89%|3|100.00%|
|2017|22|59.09%|5|100.00%|
|2018|138|89.13%|44|97.73%|
|2019|117|89.74%|24|95.83%|
|2020|67|88.06%|13|100.00%|

## Human chart review

The PDF contains one summary page and 40 deterministic condition-match charts. It deliberately includes both fills and non-fills. Each chart marks gap formation, `[L,U]`, the surrounding corridor, V6 freeze, causal first return, and the first U fill within 40 sessions when present.

## Audit

`{"DATA_2021_OR_LATER_USED": "NO", "FEATURE_USES_POST_FIRST_RETURN_INFORMATION_COUNT": 0, "MOTHER_POPULATION_SELECTED_WITH_OUTCOME_COUNT": 0, "PREDICTIVE_VALIDATION_RUN": "NO", "REPOSITORY_2024_PLUS_DATA_OPENED": "NO", "RETURN_ANALYSIS_RUN": "NO", "STRATEGY_BACKTEST_RUN": "NO", "STRUCTURAL_PATH_AFTER_H40_USED_COUNT": 0, "V6_EVENT_IDENTITY_CHANGED_COUNT": 0}`

## Next action

Review the charts for semantic fidelity. Only after that review should a separate task alter the semantic screen or reserve later years for a predictive test.
