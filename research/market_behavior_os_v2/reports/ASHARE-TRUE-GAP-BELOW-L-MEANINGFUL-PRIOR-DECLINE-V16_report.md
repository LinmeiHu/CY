# ASHARE-TRUE-GAP-BELOW-L-MEANINGFUL-PRIOR-DECLINE-V16

## Fixed rule

`pre_gap_drawdown_from_120d_peak >= 30%`; no threshold search.

## Development

`MEANINGFUL_PRIOR_DECLINE_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|V13 control|754|150.8|3.17%|5.18%|73.34%|10.21%|2.95%|-3.14%|
|D30|607|121.4|3.42%|5.46%|75.12%|10.54%|2.53%|-3.14%|

## Post-observation diagnostic

Verdict: `MEANINGFUL_PRIOR_DECLINE_POST_OBSERVATION_FAILED`.
Accepted/year: 60.0; mean: 3.17%; median: 4.16%; severe10: 10.00%.

## Governance

- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.
- D30 is one fixed economic rule; there is no candidate threshold selection.
- Signal, strict VAP/corridor, entry, A67, H20, 40 bp, K80, limits, and QD-010 are unchanged.
- 2024 data may only manage and complete pre-2024 signals.
