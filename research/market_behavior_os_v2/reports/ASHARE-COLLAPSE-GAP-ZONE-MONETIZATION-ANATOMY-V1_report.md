# ASHARE-COLLAPSE-GAP-ZONE-MONETIZATION-ANATOMY-V1

Frozen spec SHA-256: `35447ac8f0437e6e099166452447f400927bc1bfab0af50b7ec3666b34963d0a`

## Verdict

**NO_ZONE_MONETIZATION_STRUCTURE**

The common 60-session cohort contains 538 frozen E1 entries from 482 securities on 392 re-entry dates. Of 594 eligible entries, 56 are excluded outcome-blind because 60 sessions are not observable by 2021-12-31.

The zone is usually repaired and the fixed payoff is positive, but the preregistered joint positive gate is not met: 60D severe-loss10 is above the frozen 30% ceiling. This is a narrow gate failure, not evidence that structural traversal is absent. Under the frozen decision order the fallback is `NO_ZONE_MONETIZATION_STRUCTURE`; no V2 is authorized from this experiment.

## Frozen semantics

The detector, primary layer, first-return anchor, conservative E1 confirmation/next-legal-minute entry, U target, 20 bp per-side cost, T+1 sellability, PIT lineage, price-limit handling, and QD-010 corporate-action contract are unchanged. Structural fill begins at the economic first-return anchor; legal fill begins only after the frozen executable entry and can first occur on D1.

## Target geometry

|metric|mean|median|p10|p25|p75|p90|
|---|---:|---:|---:|---:|---:|---:|
|gross distance|4.34%|3.49%|2.20%|2.70%|5.07%|8.44%|
|net distance|3.92%|3.08%|1.79%|2.29%|4.65%|8.00%|

Fixed net-distance milestone rates: 0%: 99.63%, 1%: 98.14%, 2%: 85.32%, 3%: 52.23%, 5%: 21.56%.

## Structural versus legally monetizable fill

|curve|T+1|5D|10D|20D|40D|60D|
|---|---:|---:|---:|---:|---:|---:|
|structural|NA|NA|NA|80.67%|86.25%|88.48%|
|legal event-weighted|37.17%|57.99%|66.36%|79.00%|85.87%|87.92%|
|legal date-equal|NA|NA|NA|78.04%|85.68%|87.87%|

## Same-day structural fill and T+1 optionality

There are 110 same-day structural fills (20.45%). The first legal open is at/above U in 32.73%; legal U revisit rates are 71.82%/84.55%/90.00%/97.27%/97.27% at T+1/5D/20D/40D/60D. T+1-open and legal T+1-close mean net returns are 0.97% and 2.27%.

## Winner path

|horizon|winners|time-to-target median sessions|MAE median|below-L drawdown median|underwater sessions median|longest underwater run median|
|---|---:|---:|---:|---:|---:|---:|
|20D|425|2.000|-3.46%|-2.99%|1.000|1.000|
|40D|462|2.000|-3.82%|-3.49%|1.000|1.000|
|60D|473|2.000|-4.01%|-3.84%|1.000|1.000|

Rejection episodes among 60D winners: 0: N=40, median time=1.000, 1: N=45, median time=1.000, 2: N=40, median time=1.000, 3+: N=348, median time=4.000.

## Risk and unresolved tail

|horizon|severe loss 10|severe loss 20|U before loss5|U before loss10|U before loss20|unresolved|terminal net mean|MFE mean|MAE mean|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|20D|31.04%|11.15%|47.58%|66.73%|76.95%|21.00%|-13.41%|2.86%|-19.61%|
|40D|31.97%|14.13%|47.77%|67.66%|81.60%|14.13%|-18.00%|2.75%|-24.99%|
|60D|31.97%|14.68%|47.77%|67.84%|82.90%|12.08%|-21.46%|2.51%|-28.17%|

Of 20D unresolved cases, 32.74% resolve by 40D and 42.48% by 60D. Of 40D unresolved cases, 14.47% resolve by 60D.

## Survival and fixed hazards

Survival S1/S5/S10/S20/S30/S40/S50/S60: 62.83%/42.01%/33.64%/21.00%/16.91%/14.13%/13.20%/12.08%.

|window|at risk|resolved|hazard|
|---|---:|---:|---:|
|1_5|538|312|57.99%|
|6_10|226|45|19.91%|
|11_20|181|68|37.57%|
|21_40|113|37|32.74%|
|41_60|76|11|14.47%|

## Fixed FULL_OR_H payoff

|weighting|H20 mean|H20 median|H40 mean|H40 median|H60 mean|H60 median|
|---|---:|---:|---:|---:|---:|---:|
|event|0.69%|2.78%|1.38%|3.02%|1.47%|3.11%|
|date-equal|0.61%|2.85%|1.36%|3.22%|1.49%|3.29%|

## Year-by-year chronology

|year|N|median target net|legal 20/40/60|FULL_OR_H20/H40/H60 mean|H60 median|severe loss10 60D|
|---|---:|---:|---:|---:|---:|---:|
|2014|17|3.77%|94.12%/94.12%/100.00%|3.40%/3.96%/4.23%|3.77%|23.53%|
|2015|46|3.26%|93.48%/95.65%/95.65%|3.42%/3.37%/3.38%|3.93%|19.57%|
|2016|35|3.01%|80.00%/85.71%/85.71%|0.88%/1.53%/1.48%|3.05%|28.57%|
|2017|44|2.89%|72.73%/77.27%/79.55%|0.32%/0.22%/-0.86%|2.60%|34.09%|
|2018|46|2.89%|80.43%/89.13%/91.30%|2.00%/2.83%/3.12%|2.93%|28.26%|
|2019|103|3.07%|79.61%/84.47%/88.35%|0.48%/0.94%/1.59%|3.07%|25.24%|
|2020|158|2.95%|76.58%/83.54%/84.81%|-0.71%/-0.10%/-0.13%|2.79%|37.97%|
|2021|89|3.41%|74.16%/87.64%/89.89%|0.91%/2.76%/2.94%|3.46%|39.33%|

## Board and fixed structural diagnostics

### Board

|group|N|legal 60D|FULL_OR_H60 mean|severe loss10 60D|
|---|---:|---:|---:|---:|
|CHINEXT|177|89.27%|1.23%|35.03%|
|MAIN|361|87.26%|1.59%|30.47%|

### Layer structure

|group|N|legal 60D|FULL_OR_H60 mean|severe loss10 60D|
|---|---:|---:|---:|---:|
|MULTILAYER|82|91.46%|3.18%|32.93%|
|SINGLE_LAYER|456|87.28%|1.16%|31.80%|

### Persistence

|group|N|legal 60D|FULL_OR_H60 mean|severe loss10 60D|
|---|---:|---:|---:|---:|
|10_20|76|96.05%|3.94%|23.68%|
|21_60|132|92.42%|3.68%|18.94%|
|61_120|80|92.50%|2.05%|27.50%|
|GT_120|250|81.60%|-0.63%|42.80%|

### Target-distance tercile

|group|N|legal 60D|FULL_OR_H60 mean|severe loss10 60D|
|---|---:|---:|---:|---:|
|HIGH|174|84.48%|2.64%|35.06%|
|LOW|185|90.81%|0.49%|30.81%|
|MID|179|88.27%|1.35%|30.17%|

## Concentration

- formation_date: 298 dates; top-1%-date event share 12.83%; top-five fill contribution 17.76%; top-five positive-return-mass contribution 14.01%; top dates 2015-06-26, 2015-06-19, 2015-08-24, 2019-05-06, 2018-10-11.
- reentry_date: 392 dates; top-1%-date event share 3.90%; top-five fill contribution 5.29%; top-five positive-return-mass contribution 6.96%; top dates 2015-10-12, 2020-02-19, 2020-07-10, 2020-02-20, 2019-09-09.

## Correctness and scope

Audit: `{'pattern_detector_changed_count': 0, 'primary_layer_changed_count': 0, 'entry_definition_changed_count': 0, 'entry_uses_future_bar_count': 0, 'impossible_target_execution_count': 0, 'corporate_action_coordinate_violation_count': 0, 't1_same_day_sell_violation_count': 0, 'post_2021_outcome_read_count': 0}`.

No detector, layer, entry, target, horizon, subgroup, or strategy parameter was selected after outcomes. No portfolio CAGR, Sharpe, Calmar, optimized NAV, or walk-forward champion was computed. Validation 2022–2023 and repository 2024+ outcomes remained unopened.
