# ASHARE-COLLAPSE-GAP-ZONE-ENTRY-QUALITY-DISCOVERY-V1

Frozen spec SHA-256: `0408fdad2249106c78a0cd55ef6cf04890ea1824e3d16eef2d2e673d8e00cc80`

## Verdict

**ENTRY_QUALITY_PRIMARILY_FRESHNESS_DRIVEN**

This is Development-only pre-entry state discovery. V3, the primary layer, E1, U, execution and outcome clocks are unchanged. No admission replay, threshold search, Validation, or repository 2024+ read occurred.

## Cohort and base outcomes

Frozen E1 source 598; QD-010 blocks 4; complete common 60D analysis cohort 538.

|outcome|base rate|
|---|---:|
|clean_resolve_20|66.73%|
|clean_resolve_40|67.66%|
|legal_resolve_60|87.92%|
|unresolved_d60|12.08%|
|severe_unresolved_d60|10.59%|
|u_before_loss5|47.77%|
|u_before_loss10|67.84%|
|u_before_loss20|82.90%|

## Primary directional contrasts

Positive contrasts always mean better entry quality.

|dimension|clean20|U before -10|lower unresolved|lower severe unresolved|material|year|board|date|controls|supported|
|---|---:|---:|---:|---:|---|---|---|---|---|---|
|global_efficiency|8.89%|10.00%|9.44%|10.56%|True|3/7|True|True|True|False|
|recent10_efficiency|-7.61%|-7.06%|-2.72%|-5.51%|False|4/8|False|False|False|False|
|pullback_burden|-3.89%|-5.00%|0.56%|-2.22%|False|5/8|False|False|False|False|
|zone_age|17.39%|19.16%|11.04%|12.51%|True|7/8|True|True|True|True|
|cumulative_turnover|25.99%|27.67%|13.85%|15.53%|True|5/6|True|True|True|True|
|turnover_per_session|8.94%|11.17%|-1.12%|0.00%|True|6/8|True|True|False|False|

The qualifying structure is memory/freshness, not the predeclared recent-attack cleanliness hypothesis. Global path efficiency is directionally favorable, but recent10 efficiency, pullback burden, and late acceleration do not support the expected clean-approach ordering. Under the frozen verdict gate, global efficiency is descriptive and cannot replace the failed recent10 test after outcomes are seen.

## Feature availability

Cumulative turnover is available for 538/538 events; unavailable 0. Contact close location is available for 531 events; seven zero-range signal bars are null. The empirical upper contact-location quantile equals 1.0, so the frozen right-closed value bins have no distinct HIGH cell; this secondary feature is treated as tie-limited rather than re-binned after outcomes.


## Univariate bins

|feature|bin|N|clean20|clean40|legal60|U before -10|unresolved|severe unresolved|target distance|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|global_path_efficiency|HIGH|180|71.11%|72.78%|92.78%|72.78%|7.22%|5.56%|4.16%|
|global_path_efficiency|LOW|180|62.22%|62.78%|83.33%|62.78%|16.67%|16.11%|3.88%|
|global_path_efficiency|MID|178|66.85%|67.42%|87.64%|67.98%|12.36%|10.11%|3.73%|
|recent10_path_efficiency|HIGH|180|62.78%|63.33%|86.11%|63.33%|13.89%|13.89%|4.05%|
|recent10_path_efficiency|LOW|179|70.39%|70.39%|88.83%|70.39%|11.17%|8.38%|3.75%|
|recent10_path_efficiency|MID|179|67.04%|69.27%|88.83%|69.83%|11.17%|9.50%|3.97%|
|recent10_pullback_burden|HIGH|180|66.67%|67.22%|87.78%|67.78%|12.22%|9.44%|3.72%|
|recent10_pullback_burden|LOW|180|62.78%|62.78%|88.33%|62.78%|11.67%|11.67%|3.98%|
|recent10_pullback_burden|MID|178|70.79%|73.03%|87.64%|73.03%|12.36%|10.67%|4.07%|
|down_day_share_10|0.0|2|100.00%|100.00%|100.00%|100.00%|0.00%|0.00%|3.61%|
|down_day_share_10|0.111111111111|44|54.55%|54.55%|81.82%|54.55%|18.18%|18.18%|4.57%|
|down_day_share_10|0.222222222222|112|66.07%|66.96%|90.18%|66.96%|9.82%|8.93%|4.19%|
|down_day_share_10|0.333333333333|175|69.71%|70.86%|87.43%|71.43%|12.57%|11.43%|3.78%|
|down_day_share_10|0.444444444444|139|65.47%|65.47%|88.49%|65.47%|11.51%|9.35%|3.56%|
|down_day_share_10|0.555555555556|56|67.86%|71.43%|89.29%|71.43%|10.71%|10.71%|4.32%|
|down_day_share_10|0.666666666667|9|77.78%|77.78%|77.78%|77.78%|22.22%|0.00%|3.31%|
|down_day_share_10|0.777777777778|1|100.00%|100.00%|100.00%|100.00%|0.00%|0.00%|6.58%|
|higher_low_state|HIGHER_LOW|444|67.12%|68.02%|88.29%|68.24%|11.71%|10.59%|3.99%|
|higher_low_state|LOWER_LOW|94|64.89%|65.96%|86.17%|65.96%|13.83%|10.64%|3.63%|
|global_approach_speed|HIGH|179|67.60%|68.16%|92.18%|68.16%|7.82%|6.70%|4.13%|
|global_approach_speed|LOW|179|62.01%|62.57%|82.12%|63.13%|17.88%|17.32%|3.96%|
|global_approach_speed|MID|180|70.56%|72.22%|89.44%|72.22%|10.56%|7.78%|3.68%|
|late_acceleration|HIGH|179|59.78%|60.89%|86.59%|60.89%|13.41%|12.85%|3.82%|
|late_acceleration|LOW|179|74.86%|75.42%|92.18%|75.98%|7.82%|6.15%|3.87%|
|late_acceleration|MID|180|65.56%|66.67%|85.00%|66.67%|15.00%|12.78%|4.08%|
|zone_age|AGE_A|68|72.06%|75.00%|97.06%|75.00%|2.94%|2.94%|4.63%|
|zone_age|AGE_B|101|82.18%|83.17%|94.06%|84.16%|5.94%|1.98%|3.87%|
|zone_age|AGE_C|33|69.70%|69.70%|87.88%|69.70%|12.12%|9.09%|3.92%|
|zone_age|AGE_D|51|80.39%|80.39%|94.12%|80.39%|5.88%|5.88%|3.25%|
|zone_age|AGE_E|285|57.19%|57.89%|82.46%|57.89%|17.54%|16.49%|3.89%|
|cum_turnover_since_zone|HIGH|180|52.22%|52.78%|80.00%|52.78%|20.00%|19.44%|4.25%|
|cum_turnover_since_zone|LOW|179|78.21%|79.89%|93.85%|80.45%|6.15%|3.91%|4.03%|
|cum_turnover_since_zone|MID|179|69.83%|70.39%|89.94%|70.39%|10.06%|8.38%|3.49%|
|turnover_per_session|HIGH|179|61.45%|62.01%|88.27%|62.01%|11.73%|10.61%|4.11%|
|turnover_per_session|LOW|179|70.39%|72.63%|87.15%|73.18%|12.85%|10.61%|3.54%|
|turnover_per_session|MID|180|68.33%|68.33%|88.33%|68.33%|11.67%|10.56%|4.12%|
|contact_penetration|HIGH|180|62.22%|62.78%|87.78%|62.78%|12.22%|9.44%|2.55%|
|contact_penetration|LOW|179|67.60%|69.27%|87.71%|69.83%|12.29%|11.73%|5.17%|
|contact_penetration|MID|179|70.39%|70.95%|88.27%|70.95%|11.73%|10.61%|4.07%|
|contact_close_location|LOW|177|64.41%|65.54%|88.14%|65.54%|11.86%|10.73%|3.82%|
|contact_close_location|MID|354|67.80%|68.64%|87.57%|68.93%|12.43%|10.73%|3.96%|
|contact_close_location|<NA>|7|71.43%|71.43%|100.00%|71.43%|0.00%|0.00%|4.69%|
|contact_bar_return|HIGH|180|58.89%|60.56%|86.67%|60.56%|13.33%|11.67%|3.70%|
|contact_bar_return|LOW|179|75.42%|75.98%|91.62%|76.54%|8.38%|7.26%|4.07%|
|contact_bar_return|MID|179|65.92%|66.48%|85.47%|66.48%|14.53%|12.85%|4.00%|

## Primary surface extremes

|surface|better N|worse N|clean20 contrast|U-before-10 contrast|unresolved improvement|severe improvement|supported|
|---|---:|---:|---:|---:|---:|---:|---|
|age_x_cleanliness|42|102|18.63%|18.63%|8.54%|6.58%|True|
|turnover_x_cleanliness|50|53|31.06%|31.06%|8.98%|7.09%|True|
|age_x_turnover|133|178|25.76%|28.20%|15.71%|17.41%|True|
|cleanliness_x_pullback|153|142|-6.92%|-6.92%|-1.15%|-3.97%|False|

The favorable freshness×cleanliness extreme cells do not establish a cleanliness mechanism: the clean-path main effect is adverse, so these cells are dominated by freshness composition. No cell is promoted into a rule.

## Capital-memory distinction

Age versus cumulative-turnover Spearman correlation is 0.851. Higher turnover does not pass the frozen within-age distinctness test (`False`), and age does not pass the within-turnover distinctness test (`False`). Young zones are almost entirely LOW/MID turnover while 175 of 285 AGE_E events are HIGH turnover. The data therefore support a broad freshness/capital-memory decay axis, not two separately identified time-decay and ownership-rotation mechanisms.

## Year robustness

|dimension|year|better N|worse N|clean20|U before -10|lower unresolved|directional|
|---|---:|---:|---:|---:|---:|---:|---|
|global_efficiency|2014|5|2|-20.00%|-20.00%|0.00%|False|
|global_efficiency|2015|18|7|-19.05%|-19.05%|0.00%|False|
|global_efficiency|2016|14|3|-35.71%|-28.57%|-21.43%|False|
|global_efficiency|2017|10|13|36.15%|36.15%|30.77%|True|
|global_efficiency|2018|24|8|-4.17%|-4.17%|4.17%|False|
|global_efficiency|2019|46|36|11.59%|8.82%|7.97%|True|
|global_efficiency|2020|41|75|-5.46%|-5.46%|7.58%|False|
|global_efficiency|2021|22|36|32.83%|41.92%|16.67%|True|
|recent10_efficiency|2014|3|6|16.67%|16.67%|0.00%|True|
|recent10_efficiency|2015|9|19|-28.65%|-28.65%|0.00%|False|
|recent10_efficiency|2016|10|16|17.50%|17.50%|8.75%|True|
|recent10_efficiency|2017|14|13|9.89%|9.89%|24.18%|True|
|recent10_efficiency|2018|11|16|13.07%|13.07%|-2.84%|True|
|recent10_efficiency|2019|42|25|-10.95%|-8.57%|0.10%|False|
|recent10_efficiency|2020|67|49|-19.19%|-19.19%|-10.69%|False|
|recent10_efficiency|2021|24|35|-1.67%|-1.67%|0.24%|False|
|pullback_burden|2014|5|8|37.50%|37.50%|0.00%|True|
|pullback_burden|2015|8|24|-29.17%|-29.17%|8.33%|False|
|pullback_burden|2016|9|14|13.49%|13.49%|3.17%|True|
|pullback_burden|2017|15|12|10.00%|10.00%|28.33%|True|
|pullback_burden|2018|11|20|16.82%|11.82%|-4.09%|True|
|pullback_burden|2019|40|25|-5.00%|-5.00%|-2.00%|False|
|pullback_burden|2020|63|43|-16.65%|-16.65%|-4.25%|False|
|pullback_burden|2021|29|34|2.74%|-0.20%|4.36%|True|
|zone_age|2014|7|7|-14.29%|-14.29%|0.00%|False|
|zone_age|2015|36|7|40.48%|40.48%|11.51%|True|
|zone_age|2016|10|23|14.78%|24.78%|17.39%|True|
|zone_age|2017|11|30|21.82%|21.82%|14.24%|True|
|zone_age|2018|29|14|8.13%|11.58%|7.39%|True|
|zone_age|2019|24|68|24.02%|22.55%|10.54%|True|
|zone_age|2020|31|122|15.18%|15.18%|14.81%|True|
|zone_age|2021|21|65|12.82%|20.81%|1.25%|True|
|cumulative_turnover|2014|10|0|NA|NA|NA|False|
|cumulative_turnover|2015|33|2|87.88%|87.88%|50.00%|True|
|cumulative_turnover|2016|10|9|3.33%|13.33%|22.22%|True|
|cumulative_turnover|2017|9|17|-3.27%|-3.27%|-9.80%|False|
|cumulative_turnover|2018|26|10|3.08%|6.92%|-1.54%|True|
|cumulative_turnover|2019|32|31|39.01%|35.79%|19.46%|True|
|cumulative_turnover|2020|37|76|16.32%|16.32%|14.26%|True|
|cumulative_turnover|2021|22|35|37.27%|46.36%|6.88%|True|

Zone age has the expected direction in 7/8 supported years; cumulative turnover in 5/6. The effect is not 2020-only or 2015-only. Recent10 efficiency is only 4/8 and fails the frozen chronology gate.

## Board and date-equal robustness

|dimension|view|clean20|U before -10|lower unresolved|lower severe|
|---|---|---:|---:|---:|---:|
|global_efficiency|MAIN|5.93%|8.31%|10.55%|11.30%|
|global_efficiency|CHINEXT|14.85%|13.21%|7.56%|9.41%|
|global_efficiency|reentry-date equal|7.34%|8.31%|8.87%|10.30%|
|global_efficiency|formation-date equal|10.41%|11.41%|7.70%|8.75%|
|recent10_efficiency|MAIN|-11.68%|-11.68%|-4.42%|-8.89%|
|recent10_efficiency|CHINEXT|0.33%|2.33%|2.96%|2.96%|
|recent10_efficiency|reentry-date equal|-7.67%|-7.44%|-2.77%|-5.27%|
|recent10_efficiency|formation-date equal|-3.95%|-3.18%|-1.71%|-4.58%|
|pullback_burden|MAIN|-6.51%|-8.19%|-2.59%|-5.96%|
|pullback_burden|CHINEXT|1.34%|1.34%|7.84%|6.20%|
|pullback_burden|reentry-date equal|-4.95%|-6.20%|-0.25%|-3.06%|
|pullback_burden|formation-date equal|1.32%|0.34%|2.65%|0.30%|
|zone_age|MAIN|17.67%|20.58%|12.46%|12.79%|
|zone_age|CHINEXT|16.11%|15.23%|8.04%|12.04%|
|zone_age|reentry-date equal|15.56%|17.17%|10.24%|11.91%|
|zone_age|formation-date equal|16.20%|17.78%|6.74%|7.77%|
|cumulative_turnover|MAIN|21.88%|24.95%|14.33%|15.72%|
|cumulative_turnover|CHINEXT|33.75%|32.34%|14.86%|16.90%|
|cumulative_turnover|reentry-date equal|25.48%|26.79%|13.47%|14.89%|
|cumulative_turnover|formation-date equal|25.01%|26.46%|7.56%|9.65%|

Age and cumulative turnover preserve direction on Main and ChiNext, under re-entry-date equal and formation-date equal weighting, in at least two target-distance terciles, and in both layer structures. Recent10 cleanliness does not.

## Contact diagnostics

Deeper penetration and a larger signal-bar return do not improve clean resolution. LOW contact-bar return has 75.42% CLEAN_RESOLVE_20 versus 58.89% for HIGH; penetration is weak and materially confounded by target distance (mean 5.17% in LOW penetration versus 2.55% in HIGH). Contact close location is tie-limited. Contact quality therefore adds no admissible primary evidence and does not override freshness.

## Decision

The exact V3+E1+U family contains a pre-entry freshness/memory ranking representation. AGE_E and HIGH cumulative turnover are materially worse, but age and turnover are too collinear to choose a causal winner. The predeclared orderly recent10-approach hypothesis fails. A future `ASHARE-COLLAPSE-GAP-ZONE-ENTRY-ADMISSION-DEVELOPMENT-V1` is justified only as a tightly frozen freshness admission test: at most 2–3 simple translations, no new cleanliness threshold, no contact rescue, and no Validation in this experiment.

No blind charts were generated; therefore no post-signal chart bar exists. Complete surface cells, target-distance/layer controls and conditional memory tables are in the machine result.

## Audit

`{'pattern_detector_changed_count': 0, 'primary_layer_changed_count': 0, 'entry_definition_changed_count': 0, 'preentry_feature_uses_post_entry_bar_count': 0, 'preentry_daily_feature_uses_signal_day_close_count': 0, 'post_signal_bar_in_entry_quality_chart_count': 0, 'outcome_used_to_define_feature_count': 0, 'outcome_used_to_define_bin_count': 0, 'admission_rule_optimized_count': 0, 'turnover_uses_future_float_count': 0, 'corporate_action_coordinate_violation_count': 0, 'post_2021_outcome_read_count': 0}`
