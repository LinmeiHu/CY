# ASHARE-COLLAPSE-GAP-ZONE-RESOLUTION-STATE-DISCOVERY-V1

Frozen spec SHA-256: `42467094e75b5d44c7714dd090a4a171cd7e306d143420dc81bc93188a2b1017`

## Verdict

**ZONE_TAIL_RISK_ONLY_DETECTABLE_AFTER_DAMAGE**

The frozen simple state family does contain useful failure ordering, but its cleanest high-precision version (FS3) first appears after a median 13.98% mark-to-market loss. The earlier broad state (FS2) captures more failures, but contaminates 48%–55% eventual resolvers at D5/D10 and would sacrifice 27%–29% of the eventual winners. This does not justify failure-exit development.

This is causal state discovery only. No stop replay, entry search, portfolio metric, Validation, or repository 2024+ outcome was opened.

## Frozen causal contract

The unchanged V3 collapse-gap-zone detector forms the event, frozen executable E1 forms the entry, and each D1/D3/D5/D10/D20 state uses only bars available through that completed daily close. A row exists only while legal U resolution has not yet happened and the path remains observable under frozen lineage/action rules. Outcomes begin strictly after the checkpoint.

## Source and dynamic checkpoint reconciliation

Frozen executable E1 entries: 598; known QD-010 entry blocks: 4; post-entry eligible source: 594.

|checkpoint|source|resolved by checkpoint|action-censored|checkpoint missing|state unobservable|active unresolved|D60 label eligible|D60 unresolved base|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|D1|594|218|0|0|1|375|354|16.95%|
|D3|594|289|1|1|2|301|281|21.35%|
|D5|594|342|1|2|1|248|229|26.20%|
|D10|594|392|1|5|1|195|179|33.52%|
|D20|594|457|2|14|1|120|108|55.56%|

Every row closes exactly to the 594-entry post-QD-010 source denominator. Missing late checkpoints are boundary-censored rather than silently treated as failures.

## Resolution base rates

|checkpoint cohort|resolve by D20|resolve by D40|resolve by D60|severe unresolved D60|future -10% before U|future -20% before U|
|---|---:|---:|---:|---:|---:|---:|
|D1|66.94%|79.49%|83.05%|15.25%|47.46%|22.32%|
|D3|59.04%|74.20%|78.65%|19.22%|53.38%|27.76%|
|D5|50.21%|68.40%|73.80%|23.58%|62.01%|32.75%|
|D10|37.17%|59.67%|66.48%|30.17%|67.60%|38.55%|
|D20|NA|33.64%|44.44%|50.00%|78.70%|54.63%|

## Univariate checkpoint state

The table reports all predeclared bins at D5 and D10. Lift is relative to the dynamically eligible checkpoint cohort, not the old common-538 denominator.

|dimension|checkpoint|bin|N|D60 labeled|unresolved rate|lift|future -10%|median future MAE|
|---|---|---|---:|---:|---:|---:|---:|---:|
|max_progress|D5|P0|48|42|40.48%|1.54x|69.05%|-15.92%|
|max_progress|D5|P1|135|126|26.19%|1.00x|61.90%|-13.16%|
|max_progress|D5|P2|47|44|15.91%|0.61x|47.73%|-9.05%|
|max_progress|D5|P3|18|17|17.65%|0.67x|82.35%|-18.83%|
|max_progress|D10|P0|33|27|55.56%|1.66x|74.07%|-22.28%|
|max_progress|D10|P1|97|90|36.67%|1.09x|72.22%|-15.62%|
|max_progress|D10|P2|51|48|18.75%|0.56x|47.92%|-8.22%|
|max_progress|D10|P3|14|14|21.43%|0.64x|92.86%|-18.19%|
|arr|D5|A0|56|52|15.38%|0.59x|34.62%|-5.30%|
|arr|D5|A1|59|53|26.42%|1.01x|62.26%|-13.28%|
|arr|D5|A2|133|124|30.65%|1.17x|73.39%|-16.67%|
|arr|D10|A0|33|29|17.24%|0.51x|31.03%|-5.01%|
|arr|D10|A1|38|34|26.47%|0.79x|50.00%|-9.66%|
|arr|D10|A2|124|116|39.66%|1.18x|81.90%|-19.01%|
|distance_below_l|D5|Z0|36|33|9.09%|0.35x|27.27%|-4.12%|
|distance_below_l|D5|Z1|82|77|18.18%|0.69x|44.16%|-7.57%|
|distance_below_l|D5|Z2|130|119|36.13%|1.38x|83.19%|-19.19%|
|distance_below_l|D10|Z0|30|30|10.00%|0.30x|16.67%|-1.14%|
|distance_below_l|D10|Z1|59|50|20.00%|0.60x|50.00%|-9.92%|
|distance_below_l|D10|Z2|106|99|47.47%|1.42x|91.92%|-22.87%|
|recovery_to_l|D5|R0|103|93|43.01%|1.64x|91.40%|-23.01%|
|recovery_to_l|D5|R1|68|63|15.87%|0.61x|50.79%|-10.06%|
|recovery_to_l|D5|R2|77|73|13.70%|0.52x|34.25%|-5.39%|
|recovery_to_l|D10|R0|93|83|48.19%|1.44x|92.77%|-23.39%|
|recovery_to_l|D10|R1|47|44|29.55%|0.88x|68.18%|-12.30%|
|recovery_to_l|D10|R2|55|52|13.46%|0.40x|26.92%|-3.92%|
|underwater|D5|HIGH|204|185|28.11%|1.07x|67.03%|-15.41%|
|underwater|D5|LOW|15|15|13.33%|0.51x|26.67%|-5.25%|
|underwater|D5|MID|29|29|20.69%|0.79x|48.28%|-10.20%|
|underwater|D10|HIGH|167|151|37.09%|1.11x|74.83%|-16.24%|
|underwater|D10|LOW|11|11|0.00%|0.00x|9.09%|-3.80%|
|underwater|D10|MID|17|17|23.53%|0.70x|41.18%|-5.91%|
|recovery_3d|D5|DOWN|104|95|35.79%|1.37x|81.05%|-18.91%|
|recovery_3d|D5|FLAT|69|63|26.98%|1.03x|60.32%|-13.54%|
|recovery_3d|D5|UP|75|71|12.68%|0.48x|38.03%|-7.68%|
|recovery_3d|D10|DOWN|82|77|37.66%|1.12x|76.62%|-16.07%|
|recovery_3d|D10|FLAT|39|32|43.75%|1.31x|68.75%|-14.52%|
|recovery_3d|D10|UP|74|70|24.29%|0.72x|57.14%|-12.58%|
|low_structure|D5|HIGHER_LOW|73|65|13.85%|0.53x|41.54%|-8.02%|
|low_structure|D5|LOWER_LOW|172|161|31.68%|1.21x|71.43%|-15.68%|
|low_structure|D5|ROUGHLY_EQUAL|3|3|0.00%|0.00x|0.00%|-6.78%|
|low_structure|D10|HIGHER_LOW|87|80|23.75%|0.71x|57.50%|-11.37%|
|low_structure|D10|LOWER_LOW|106|97|42.27%|1.26x|75.26%|-16.07%|
|low_structure|D10|ROUGHLY_EQUAL|2|2|0.00%|0.00x|100.00%|-12.42%|

Main directional reading: low progress, greater distance below L, weak recovery, downward three-session direction, and lower-low structure all identify worse conditional paths. Underwater share by itself is weak. Distance below L adds information beyond percentage damage because the strongest frozen interaction is low progress plus distance greater than one zone width.

## Predeclared state surfaces

Cells with at least 10 checkpoint observations are shown; no cell was selected to create a new rule.

|surface|checkpoint|cell|N|unresolved rate|lift|
|---|---|---|---:|---:|---:|
|progress_x_arr|D5|P0|A1|14|30.77%|1.17x|
|progress_x_arr|D5|P0|A2|26|45.45%|1.73x|
|progress_x_arr|D5|P1|A0|35|12.50%|0.48x|
|progress_x_arr|D5|P1|A1|32|28.57%|1.09x|
|progress_x_arr|D5|P1|A2|68|31.82%|1.21x|
|progress_x_arr|D5|P2|A0|13|7.69%|0.29x|
|progress_x_arr|D5|P2|A1|12|18.18%|0.69x|
|progress_x_arr|D5|P2|A2|22|20.00%|0.76x|
|progress_x_arr|D5|P3|A2|17|18.75%|0.72x|
|progress_x_arr|D10|P0|A2|27|56.52%|1.69x|
|progress_x_arr|D10|P1|A0|18|20.00%|0.60x|
|progress_x_arr|D10|P1|A1|20|33.33%|0.99x|
|progress_x_arr|D10|P1|A2|59|42.11%|1.26x|
|progress_x_arr|D10|P2|A0|12|8.33%|0.25x|
|progress_x_arr|D10|P2|A1|15|14.29%|0.43x|
|progress_x_arr|D10|P2|A2|24|27.27%|0.81x|
|progress_x_arr|D10|P3|A2|14|21.43%|0.64x|
|progress_x_distance|D5|P0|Z1|20|16.67%|0.64x|
|progress_x_distance|D5|P0|Z2|27|58.33%|2.23x|
|progress_x_distance|D5|P1|Z0|23|9.52%|0.36x|
|progress_x_distance|D5|P1|Z1|46|22.73%|0.87x|
|progress_x_distance|D5|P1|Z2|66|34.43%|1.31x|
|progress_x_distance|D5|P2|Z0|12|8.33%|0.32x|
|progress_x_distance|D5|P2|Z1|13|8.33%|0.32x|
|progress_x_distance|D5|P2|Z2|22|25.00%|0.95x|
|progress_x_distance|D5|P3|Z2|15|21.43%|0.82x|
|progress_x_distance|D10|P0|Z2|23|73.68%|2.20x|
|progress_x_distance|D10|P1|Z1|36|22.58%|0.67x|
|progress_x_distance|D10|P1|Z2|52|48.00%|1.43x|
|progress_x_distance|D10|P2|Z0|20|5.00%|0.15x|
|progress_x_distance|D10|P2|Z1|12|20.00%|0.60x|
|progress_x_distance|D10|P2|Z2|19|33.33%|0.99x|
|progress_x_distance|D10|P3|Z2|12|25.00%|0.75x|
|distance_x_recovery|D5|Z1|R0|11|22.22%|0.76x|
|distance_x_recovery|D5|Z1|R1|32|16.67%|0.57x|
|distance_x_recovery|D5|Z1|R2|39|18.42%|0.63x|
|distance_x_recovery|D5|Z2|R0|92|45.24%|1.56x|
|distance_x_recovery|D5|Z2|R1|36|15.15%|0.52x|
|distance_x_recovery|D10|Z1|R0|14|20.00%|0.52x|
|distance_x_recovery|D10|Z1|R1|20|22.22%|0.58x|
|distance_x_recovery|D10|Z1|R2|25|18.18%|0.48x|
|distance_x_recovery|D10|Z2|R0|79|52.05%|1.36x|
|distance_x_recovery|D10|Z2|R1|27|34.62%|0.90x|

The strongest descriptive cells are P0×Z2: 58.33% unresolved at D5 (2.23x base) and 73.68% at D10 (2.20x). This interaction is economically coherent, but it is not itself an authorized exit rule and its chronology/coverage gates do not support promotion.

## Predeclared failure states

|state|checkpoint|N|precision|lift|tail capture|resolver contamination|winners sacrificed|
|---|---|---:|---:|---:|---:|---:|---:|
|FS1|D1|21|38.10%|2.25x|13.33%|61.90%|4.42%|
|FS1|D3|24|37.50%|1.76x|15.00%|62.50%|6.79%|
|FS1|D5|22|45.45%|1.73x|16.67%|54.55%|7.10%|
|FS1|D10|23|56.52%|1.69x|21.67%|43.48%|8.40%|
|FS1|D20|14|92.86%|1.67x|21.67%|7.14%|2.08%|
|FS2|D1|87|29.89%|1.76x|43.33%|70.11%|20.75%|
|FS2|D3|92|33.70%|1.58x|51.67%|66.30%|27.60%|
|FS2|D5|84|45.24%|1.73x|63.33%|54.76%|27.22%|
|FS2|D10|73|52.05%|1.55x|63.33%|47.95%|29.41%|
|FS2|D20|56|78.57%|1.41x|73.33%|21.43%|25.00%|
|FS3|D3|16|50.00%|2.34x|13.33%|50.00%|3.62%|
|FS3|D5|11|72.73%|2.78x|13.33%|27.27%|1.78%|
|FS3|D10|10|80.00%|2.39x|13.33%|20.00%|1.68%|
|FS3|D20|5|100.00%|1.80x|8.33%|0.00%|0.00%|

## First-detection timing and path consequence

|state|N|median checkpoint|median loss|before -5|-5 to -10|after -10|after -20|
|---|---:|---:|---:|---:|---:|---:|---:|
|FS1|36|1.0|-9.79%|19.44%|33.33%|47.22%|2.78%|
|FS2|176|3.0|-8.92%|9.66%|51.14%|39.20%|4.55%|
|FS3|24|3.0|-13.98%|12.50%|8.33%|79.17%|20.83%|

|state|path|N|loss at first trigger|later sessions to U / terminal D60 net|future MAE|additional drawdown / D60 distance below L|
|---|---|---:|---:|---:|---:|---:|
|FS1|eventual resolver false alarm|23|-9.65%|9.0 sessions|-13.14%|-2.24%|
|FS1|D60 unresolved failure|13|-10.36%|-24.98%|-32.79%|5.42W|
|FS2|eventual resolver false alarm|121|-8.46%|10.0 sessions|-13.24%|-3.73%|
|FS2|D60 unresolved failure|55|-9.88%|-23.02%|-28.17%|4.37W|
|FS3|eventual resolver false alarm|11|-15.26%|10.0 sessions|-16.43%|-4.25%|
|FS3|D60 unresolved failure|13|-13.71%|-24.98%|-32.79%|5.42W|

## Checkpoint evolution

|transition|path|N|median Δ progress|median Δ ARR|median Δ distance below L|median Δ recovery|
|---|---|---:|---:|---:|---:|---:|
|D1_D3|resolver|221|0.000|0.289|0.024|0.034|
|D1_D3|unresolved|60|0.000|0.547|0.426|-0.092|
|D3_D5|resolver|169|0.000|0.000|0.018|0.055|
|D3_D5|unresolved|60|0.000|0.305|0.313|-0.036|
|D5_D10|resolver|119|0.000|0.122|0.000|0.070|
|D5_D10|unresolved|60|0.000|0.533|0.543|-0.001|
|D10_D20|resolver|48|0.000|0.031|-0.230|0.216|
|D10_D20|unresolved|60|0.000|0.774|0.767|-0.015|

Unresolved paths progressively accumulate ARR and distance below L; eventual resolvers show much smaller damage accumulation and improving recovery. That distinction is real descriptively, but much of it arrives only after meaningful loss.

## Chronology and board robustness

|checkpoint|year|labeled N|base unresolved|FS2 N|FS2 precision|FS2 lift|
|---|---:|---:|---:|---:|---:|---:|
|D5|2014|9|0.00%|2|0.00%|NAx|
|D5|2015|18|5.56%|2|50.00%|9.00x|
|D5|2016|17|29.41%|4|25.00%|0.85x|
|D5|2017|19|47.37%|5|80.00%|1.69x|
|D5|2018|18|16.67%|7|28.57%|1.71x|
|D5|2019|36|27.78%|15|46.67%|1.68x|
|D5|2020|61|39.34%|28|60.71%|1.54x|
|D5|2021|51|15.69%|21|28.57%|1.82x|
|D10|2014|6|0.00%|1|0.00%|NAx|
|D10|2015|13|7.69%|2|50.00%|6.50x|
|D10|2016|12|41.67%|4|50.00%|1.20x|
|D10|2017|18|50.00%|7|71.43%|1.43x|
|D10|2018|15|20.00%|6|16.67%|0.83x|
|D10|2019|30|33.33%|10|50.00%|1.50x|
|D10|2020|47|51.06%|28|64.29%|1.26x|
|D10|2021|38|21.05%|15|40.00%|1.90x|

Sparse annual cells prevent a strong year-stability claim for the high-precision FS3 state. FS2 is directionally positive in most supported years but not uniformly, including a D10 reversal in 2018.

|checkpoint|board|labeled N|base unresolved|FS1 lift|FS2 lift|FS3 lift|
|---|---|---:|---:|---:|---:|---:|
|D5|CHINEXT|74|24.32%|1.64x|1.62x|2.47x|
|D5|MAIN|155|27.10%|1.85x|1.81x|3.08x|
|D10|CHINEXT|55|32.73%|1.53x|1.73x|1.53x|
|D10|MAIN|124|33.87%|1.82x|1.48x|2.58x|

The basic relation is present on Main Board and ChiNext. The machine result also contains event-weighted, re-entry-date-equal, formation-date-equal, persistence-stratum, and frozen target-distance-tercile controls. The full promotion gate fails date robustness and/or concentration controls depending on state.

## Decision

The non-resolution tail is partly predictable from simple path state, especially from the interaction of low progress and large distance below L. Recovery state helps distinguish some normal rejection winners, but not enough to create a low-contamination early failure state. FS3 is cleaner but late; FS2 is earlier but broad. Therefore `ASHARE-COLLAPSE-GAP-ZONE-FAILURE-EXIT-DEVELOPMENT-V1` is not justified.

The next scientifically distinct question, if this pattern receives more budget, is a separately frozen `ASHARE-COLLAPSE-GAP-ZONE-ENTRY-QUALITY-DISCOVERY-V1`: determine whether causal pre-entry approach state can avoid later non-resolvers. It must not reuse these post-entry outcomes to tune entry rules in this experiment.

## Correctness audit

Audit: `{'pattern_detector_changed_count': 0, 'primary_layer_changed_count': 0, 'entry_definition_changed_count': 0, 'checkpoint_uses_future_bar_count': 0, 'post_checkpoint_bar_in_state_feature_count': 0, 'post_checkpoint_bar_in_state_chart_count': 0, 'target_result_used_to_define_state_count': 0, 'stop_rule_optimized_count': 0, 'checkpoint_clock_failure_count': 0, 'state_future_bar_count': 0, 't1_semantic_violation_count': 0, 'corporate_action_coordinate_violation_count': 0, 'post_2021_outcome_read_count': 0}`

Validation opened: `False`. Repository 2024+ data opened: `False`.

Complete machine-readable univariate bins, surfaces, timing paths, date-equal controls, robustness tables, and verdict evidence are in the result JSON.
