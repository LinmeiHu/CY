# ASHARE-TRUE-GAP-BELOW-L-HARD-LOSS-BOUNDARY-V15

## Development

`HARD_LOSS_BOUNDARY_DEVELOPMENT_CANDIDATE`

|Rule|Accepted|Accepted/year|Mean|Median|Win|Severe10|Stops|CAGR|MaxDD|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|S0_NO_STOP|754|150.8|3.17%|5.18%|73.34%|10.21%|0|2.95%|-3.14%|
|S8_DAILY_CLOSE|763|152.6|2.66%|4.83%|69.07%|11.40%|176|2.50%|-3.24%|
|S10_DAILY_CLOSE|763|152.6|2.87%|5.04%|71.43%|16.25%|127|2.71%|-3.33%|
|S12_DAILY_CLOSE|760|152.0|2.93%|5.10%|72.24%|13.68%|90|2.74%|-3.33%|

## Post-observation diagnostic

Selected rule: `S0_NO_STOP`.
Verdict: `HARD_LOSS_BOUNDARY_POST_OBSERVATION_FAILED`.
Accepted/year: 73.0; mean: 2.70%; median: 3.92%; severe10: 11.64%.

## Governance

- Frequency means at least 50 accepted trades/year; there is no upper cap.
- Stop information is a completed valid daily close; execution is the next legal open with T+1 and actual gap-through handling.
- Signal, entry, A67, H20, 40 bp, K80, limits, and QD-010 are unchanged.
- 2024 data may only manage and complete pre-2024 signals.
