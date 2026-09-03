# ASHARE-ALL-TRUE-GAP-LOW-INVENTORY-FILL-PATTERN-DISCOVERY-V2

## Status

`STOPPED_FOR_HUMAN_PATTERN_REVIEW`

This is a 2014-2020 same-sample structural pattern description. It reconstructs the full governed Main/ChiNext true-gap universe directly from PIT daily rows and does not use a V6 CORE candidate gate.

## Funnel

|Stage|Count|
|---|---:|
|all_true_gaps|88785|
|daily_exact_history|22709|
|daily_vap_eligible|3151|
|exact_120x241_minute_history|3151|
|exact_first_return_minute|2209|
|low_inside_and_corridor_inventory|2209|
|low_inside_and_corridor_inventory_before_return_minute_check|2237|
|low_inside_inventory|2639|
|pristine_first_return|11781|
|width_ge_1pct|37459|

## Structural fill

|Population|N|Symbols|5D U fill|10D U fill|20D U fill|40D U fill|
|---|---:|---:|---:|---:|---:|---:|
|Low-inventory mother|2209|1446|75.33%|82.48%|88.28%|91.22%|
|Simple conditions|305|296|85.25%|90.16%|95.74%|97.38%|

## Descriptive conditions

1. `gap_width_pct <= 0.0178571` (Q50; N=1105, 20D fill=93.48%, pooled lift=+5.21%, positive-lift years=6).
2. `pre_gap_inside_density_relative_local <= 0.102375` (Q30; N=305, 20D fill=95.74%, pooled lift=+7.46%, positive-lift years=7).

These conditions were discovered and measured on the same 2014-2020 sample. They are not predictive evidence and are not a strategy.

## Concentration and interpretation

The final 305-event description spans 58 formation dates. The largest date is 2018-10-11 with 120 events (39.34%); the top five dates contribute 74.75%. Formation-date-equal 20D fill is 94.54%.
Same-day structural U fill accounts for 163 events (53.44%). This is structural geometry, not executable headroom.
Successful mother-population cases are descriptively associated with narrower gaps, longer peak-to-gap histories, deeper prior drawdowns, less acute 20-day run-up, and lower post-gap lower-corridor turnover. These secondary contrasts did not replace the frozen two-condition selector.

## Calendar-year view

|Year|Mother N|Mother 20D|Rule N|Rule 20D|
|---:|---:|---:|---:|---:|
|2014|39|79.49%|2|100.00%|
|2015|153|88.24%|1|100.00%|
|2016|69|86.96%|1|100.00%|
|2017|101|75.25%|18|77.78%|
|2018|868|90.90%|192|95.83%|
|2019|604|89.90%|79|98.73%|
|2020|375|84.27%|12|100.00%|

## Chart book

The PDF contains one summary page plus all 305 final condition matches. Every page shows the full gap-to-return lifecycle, a local first-return view, `[L,U]`, the surrounding corridor, and the 120-session pre-gap turnover-at-price profile.

## Audit

`{"DATA_2021_OR_LATER_USED": "NO", "FEATURE_USES_POST_FIRST_RETURN_INFORMATION_COUNT": 0, "MOTHER_POPULATION_SELECTED_WITH_OUTCOME_COUNT": 0, "PREDICTIVE_VALIDATION_RUN": "NO", "PRE_PERSISTENCE_TOUCH_RESET_AS_FIRST_RETURN_COUNT": 0, "REPOSITORY_2024_PLUS_DATA_OPENED": "NO", "RETURN_ANALYSIS_RUN": "NO", "STRATEGY_BACKTEST_RUN": "NO", "V6_COLLAPSE_CLUSTER_GATE_USED": "NO", "V6_CORE_CANDIDATE_GATE_USED": "NO"}`

No returns, PnL, trading replay, prediction, 2021+ data, or repository 2024+ data were opened. Stop for human review.
