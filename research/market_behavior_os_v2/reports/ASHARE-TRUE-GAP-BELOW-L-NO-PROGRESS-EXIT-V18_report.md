# ASHARE-TRUE-GAP-BELOW-L-NO-PROGRESS-EXIT-V18

## Fixed failure exit

At D10 close: maximum progress < half the A67 target distance and close <= entry; exit next legal minute open.

## Development

`NO_PROGRESS_EXIT_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Exits|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|V17 control|575|115.0|3.74%|5.60%|76.52%|9.57%|0|2.64%|-3.19%|
|D10 no progress|578|115.6|3.44%|5.29%|70.59%|7.09%|114|2.45%|-2.83%|

## Post-observation diagnostic

Verdict: `NO_PROGRESS_EXIT_POST_OBSERVATION_FAILED`.
Accepted/year: 54.5; mean: 2.89%; median: 2.65%; severe10: 8.26%; exits: 32.

## Governance

- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.
- D10/half-target is one fixed causal failure state; no stop grid is searched.
- Signals, entries, target, fallback H20, costs, portfolio, limits, T+1, and QD-010 are unchanged.
- 2024 data may only manage and complete pre-2024 signals.
