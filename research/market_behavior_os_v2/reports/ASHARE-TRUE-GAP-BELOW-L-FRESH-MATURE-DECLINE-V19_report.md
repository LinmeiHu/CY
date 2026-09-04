# ASHARE-TRUE-GAP-BELOW-L-FRESH-MATURE-DECLINE-V19

## Fixed rule

`D30 + M20 + gap_age <= 30`; no age search.

## Development

`FRESH_MATURE_DECLINE_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|V17 control|575|115.0|3.74%|5.60%|76.52%|9.57%|2.64%|-3.19%|
|AGE30|557|111.4|3.80%|5.64%|77.02%|9.52%|2.59%|-3.19%|

## Post-observation diagnostic

Verdict: `FRESH_MATURE_DECLINE_POST_OBSERVATION_FAILED`.
Accepted/year: 52.0; mean: 3.66%; median: 4.69%; severe10: 8.65%.

## Governance

- Frequency is a floor of at least 50 accepted trades/year, never a target or upper cap.
- AGE30 is one fixed memory-state condition; no age family is searched.
- All V17 signal, entry, A67, H20, cost, portfolio, and PIT semantics are unchanged.
- 2024 data may only manage and complete pre-2024 signals.
