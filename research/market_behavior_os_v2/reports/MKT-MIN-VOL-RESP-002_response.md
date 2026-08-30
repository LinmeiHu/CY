# MKT-MIN-VOL-RESP-002 continuous future-volatility response

## Boundary

- Status: `COMPLETE_NO_REPLICATING_FUTURE_VOLATILITY_RESPONSE`
- Predictor rows: 10,696; 2018-07-03..2023-12-29.
- Future responses become available only at 15:30 on t+h; they are never predictors at t and create no action.
- Price returns, strategy outcomes, raw minutes, failed path fields, discrete states, and CY-011 read: **none**.
- Association is not causality, return prediction, habitat fitness, or a trading rule.

## Partial-rank response

| Horizon | Block | Median partial rho | Median absolute partial rho | Group sign agreement | Minimum n/group |
|---:|---|---:|---:|---:|---:|
| 1 | discovery | 0.033 | 0.033 | 8/8 | 728 |
| 1 | confirmation | -0.092 | 0.092 | 8/8 | 483 |
| 3 | discovery | 0.060 | 0.060 | 8/8 | 728 |
| 3 | confirmation | 0.010 | 0.013 | 6/8 | 481 |
| 5 | discovery | -0.017 | 0.023 | 5/8 | 728 |
| 5 | confirmation | -0.015 | 0.018 | 6/8 | 479 |

## Fixed phase-zero non-overlapping h=5

| Block | Median partial rho | Median absolute partial rho | Group sign agreement | Minimum n/group |
|---|---:|---:|---:|---:|
| discovery | -0.005 | 0.019 | 5/8 | 146 |
| confirmation | -0.019 | 0.019 | 6/8 | 96 |

## Gates

- `coverage`: PASS
- `primary_effect`: FAIL
- `primary_sign_replication`: PASS
- `primary_group_portability`: FAIL
- `neighbor_horizons`: FAIL
- `nonoverlap_primary`: FAIL

## Reproducibility

- Spec SHA-256: `9ef7a0b2aff42a9bded178d63d1f3bca2ae1dad033d8d30378adf490fa51a2d9`
- Output panel SHA-256: `f0ca616248726b27fa4cbcabe7059d690038dd3d24222259693d8fea7a756ec7`
