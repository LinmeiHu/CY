# ASHARE-TRUE-GAP-BELOW-L-DRY-BASE-REVERSAL-V22

## Fixed rule

Frozen V13 prior-high reversal population plus one natural condition: `dry3 <= 1`. Post-V13 D30/M20/AGE30/H6 gates are not carried forward.

## Development

`DRY_BASE_REVERSAL_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|V20 reference|523|104.6|3.96%|6.16%|76.48%|9.94%|2.54%|-3.18%|
|V22 dry base|581|116.2|3.23%|5.12%|73.49%|8.78%|2.38%|-1.98%|

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2017|68|0.23%|2.55%|58.82%|-0.05%|
|2018|254|4.91%|5.96%|84.25%|8.12%|
|2019|103|2.76%|4.15%|69.90%|1.81%|
|2020|72|1.91%|4.60%|65.28%|1.04%|
|2021|84|2.29%|3.98%|64.29%|1.07%|

## Post-observation diagnostic

Verdict: `DRY_BASE_REVERSAL_POST_OBSERVATION_FAILED`.
Accepted/year: 50.5; mean: 2.17%; median: 3.66%; win: 63.37%; severe10: 12.87%.

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2022|64|4.40%|6.24%|73.44%|1.73%|
|2023|37|-1.70%|-1.75%|45.95%|-0.09%|

## Governance

- dry3 uses only the three and 19 completed sessions preceding the signal.
- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.
- No exit rule, target, horizon, cost, portfolio, T+1, limit, suspension, or QD-010 semantic changed.
- 2022-2023 is post-observation diagnostic evidence, not pristine validation.
- 2024 data may only manage and complete pre-2024 signals.
