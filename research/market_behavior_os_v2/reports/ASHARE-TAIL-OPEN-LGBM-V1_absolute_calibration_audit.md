# A-share Tail-to-Open LightGBM V1 — Absolute-prediction calibration audit

Classification: `ABSOLUTE_SCORE_RANKING_ONLY`.

Only accepted 2018–2021 OOF predictions and embedded realized labels were read. No refit, rescore, Validation, Final OOS, threshold search, or strategy replay occurred.

## Canonical predicted-net > 0 condition

| Period | Observations | Active days | Stocks / active day | Gross | Net | Win rate | Coverage |
|---|---:|---:|---:|---:|---:|---:|---:|
| pooled | 7,968 | 55 | 144.87 | -0.874% | -1.269% | 35.07% | 99.70% |
| 2018 | 37 | 12 | 3.08 | 0.572% | 0.170% | 45.95% | 100.00% |
| 2019 | 5,446 | 21 | 259.33 | -0.668% | -1.065% | 43.17% | 99.58% |
| 2020 | 2,464 | 10 | 246.40 | -1.361% | -1.755% | 16.89% | 99.96% |
| 2021 | 21 | 12 | 1.75 | 0.702% | 0.300% | 57.14% | 100.00% |

## Fixed threshold diagnostics (pooled)

| Threshold | Observations | Active days | Gross | Net |
|---|---:|---:|---:|---:|
| gt_10bp | 4,516 | 30 | -1.016% | -1.411% |
| gt_20bp | 2,555 | 19 | -0.905% | -1.300% |
| gt_40bp | 852 | 8 | 0.129% | -0.270% |

## Calibration regression

Pooled intercept `0.0686%`, slope `1.093`, R² `0.0660`.
