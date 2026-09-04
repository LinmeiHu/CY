# ASHARE-TRUE-GAP-BELOW-L-PROGRESS-PROTECTION-V21

## Fixed rule

V20 unchanged. After the post-entry high reaches 50% of the fixed A67 path, the first completed daily close at or below entry exits at the next legal minute open.

## Development

`PROGRESS_PROTECTION_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Exits|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|V20 control|523|104.6|3.96%|6.16%|76.48%|9.94%|0|2.54%|-3.18%|
|V21|525|105.0|3.69%|5.46%|67.62%|7.05%|101|2.38%|-2.71%|

### Development chronology

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2017|53|1.34%|0.95%|54.72%|0.37%|
|2018|308|5.01%|6.75%|75.97%|10.00%|
|2019|56|3.66%|4.36%|64.29%|1.28%|
|2020|43|-0.91%|-1.08%|44.19%|-0.17%|
|2021|65|2.42%|4.06%|56.92%|1.06%|

## Post-observation diagnostic

Verdict: `PROGRESS_PROTECTION_POST_OBSERVATION_FAILED`.
Accepted/year: 51.5; mean: 3.72%; median: 2.65%; win: 58.25%; severe10: 5.83%; exits: 20.

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2022|71|5.19%|6.08%|67.61%|2.28%|
|2023|32|0.45%|-1.32%|37.50%|0.28%|

## Governance

- Frequency must remain strictly above 50 accepted trades/year; there is no upper cap.
- V21 uses exactly one 50%-path activation and one entry-cost close failure line.
- Signals, entries, A67, fallback H20, costs, portfolio, T+1, limits, suspensions, and QD-010 are unchanged.
- 2022-2023 is post-observation diagnostic evidence, not pristine validation.
- 2024 data may only manage and complete pre-2024 signals.
