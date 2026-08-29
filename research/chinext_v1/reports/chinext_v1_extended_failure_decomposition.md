# ChinNext V1 — 2018–2021 frozen first-view failure decomposition

> Offline only: no replay, new trade, NAV, strategy change, or 2022–2025 performance use.

- V1_EXTENDED_HISTORY_GENERALIZATION: `MIXED`
- 2018_2021_STATUS: `IN_SAMPLE_MECHANISM_RESEARCH_AFTER_FROZEN_V1_FIRST_VIEW`
- 2022_2025_USED_FOR_V2_SELECTION: `NO`
- FORMAL_REPLAY_EXECUTIONS: `0`

## Annual pattern

| Year | Trades | Portfolio return | Win rate | Median trade | Mean trade |
|---:|---:|---:|---:|---:|---:|
| 2018 | 11 | -3.78% | 18.18% | -3.47% | -3.47% |
| 2019 | 47 | 23.49% | 48.94% | -0.30% | 3.98% |
| 2020 | 74 | 5.27% | 47.30% | -0.32% | 1.66% |
| 2021 | 62 | 31.78% | 45.16% | -1.00% | 5.15% |

## Structural result

- TOTAL_RETURN: `64.8224%`
- MAX_DRAWDOWN: `-20.7627%`
- MEDIAN_TRADE: `-0.9705%`
- MEAN_TRADE: `3.0456%`
- TOP20_PNL_CONCENTRATION: `73.5179%`
- RETURN_EX_BEST20: `-50.1573%`

## Exit interaction

| Exit lineage | Trades | Win rate | Median return | Realized P&L |
|---|---:|---:|---:|---:|
| INDIVIDUAL_MA30_X2_AND_SET_REMOVAL | 39 | 25.64% | -6.93% | -282,649.41 |
| MARKET_EMERGENCY_X0.96 | 14 | 64.29% | 1.76% | 77,591.58 |
| MARKET_MA20_X2 | 134 | 50.75% | 0.13% | 906,657.97 |
| SET_REMOVAL | 7 | 14.29% | -5.52% | -53,376.42 |

## Interpretation boundary

MFE, MAE, path, feature, month, and exit-lineage relationships are ex-post descriptive evidence used only to rank mechanism hypotheses. They are not causal counterfactuals or standalone trading rules. The full machine-readable distributions and frozen hashes are in the companion JSON.
