# Phase 4 — MFE Monetization

OC-EXP-P4-001: **PASS** on `84` opportunity20 cycles (`32` opportunity50).

## MFE bands

| Band | N | Terminal median | Capture median | Positive capture | Right-tail conversion | Giveback median | Time-to-MFE fraction |
|---|---:|---:|---:|---:|---:|---:|---:|
| MFE20_TO_50 | 52 | 10.21% | 33.58% | 88.46% | 17.31% | 19.03% | 0.72 |
| MFE_GE_50 | 32 | 48.28% | 58.37% | 100.00% | 93.75% | 35.06% | 0.75 |

## Breadth conditional on MFE magnitude and year

| Outcome | N | rho | Year + / - | LOYO + / - |
|---|---:|---:|---:|---:|
| opportunity20_capture | 81 | 0.130 | 4 / 2 | 7 / 0 |
| terminal_return | 81 | 0.079 | 4 / 2 | 7 / 0 |
| positive_capture | 81 | 0.059 | 1 / 4 | 6 / 1 |
| right_tail_conversion20 | 81 | 0.038 | 4 / 2 | 7 / 0 |
| post_mfe_giveback | 81 | -0.187 | 1 / 5 | 0 / 7 |

## Strongest path associations

| Path variable | Capture outcome | N | rho(year+MFE) | q(50) | Year + / - | LOYO + / - |
|---|---|---:|---:|---:|---:|---:|
| days_from_peak_to_exit | opportunity20_capture | 84 | -0.477 | 0.000 | 1 / 5 | 0 / 7 |
| days_from_peak_to_exit | terminal_return | 84 | -0.451 | 0.001 | 1 / 5 | 0 / 7 |
| holding_path_mean_close_return | terminal_return | 84 | 0.438 | 0.001 | 4 / 2 | 7 / 0 |
| post_peak_decay_rate | post_mfe_giveback | 84 | 0.433 | 0.001 | 5 / 1 | 7 / 0 |
| days_from_peak_to_exit | post_mfe_giveback | 84 | 0.433 | 0.001 | 5 / 1 | 7 / 0 |
| time_to_mfe_fraction | terminal_return | 84 | 0.419 | 0.001 | 4 / 2 | 7 / 0 |
| time_to_mfe_fraction | opportunity20_capture | 84 | 0.400 | 0.002 | 5 / 1 | 7 / 0 |
| post_peak_decay_rate | opportunity20_capture | 84 | -0.376 | 0.005 | 1 / 5 | 0 / 7 |
| holding_path_mean_close_return | opportunity20_capture | 84 | 0.348 | 0.011 | 5 / 1 | 7 / 0 |
| days_from_peak_to_exit | right_tail_conversion20 | 84 | -0.338 | 0.013 | 1 / 5 | 0 / 7 |
| holding_path_mean_close_return | post_mfe_giveback | 84 | -0.333 | 0.014 | 1 / 5 | 0 / 7 |
| time_to_mfe_fraction | post_mfe_giveback | 84 | -0.293 | 0.041 | 1 / 5 | 0 / 7 |
| time_to_mfe_fraction | right_tail_conversion20 | 84 | 0.264 | 0.076 | 5 / 1 | 7 / 0 |
| post_peak_decay_rate | terminal_return | 84 | -0.263 | 0.076 | 2 / 4 | 0 / 7 |
| post_peak_decay_rate | right_tail_conversion20 | 84 | -0.257 | 0.083 | 1 / 5 | 0 / 7 |
| holding_path_mean_close_return | positive_capture | 84 | 0.243 | 0.107 | 3 / 3 | 7 / 0 |
| holding_trading_days | post_mfe_giveback | 84 | 0.233 | 0.124 | 4 / 2 | 7 / 0 |
| holding_trading_days | opportunity20_capture | 84 | -0.228 | 0.131 | 2 / 4 | 0 / 7 |

Post-peak giveback, mean close return, and decay contain realized path information. They locate leakage but are not decision-time predictors and cannot pass the strategy gate by themselves.
