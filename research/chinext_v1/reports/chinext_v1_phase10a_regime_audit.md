# ChinNext V1 Phase 10A — zero-replay regime feature audit

FORMAL_REPLAY_EXECUTIONS: `0`; NEW_TRADES: `0`; NEW_NAV: `0`; PIT_REBUILT: `NO`.
Feature spec frozen before outcome analysis: `eef08f1af256d8908658cf5d7c518b1871cf16dddbf73f5c85c253a02617461e`.

## Data governance
399102.SZ local completed-bar anchor is used descriptively; PIT breadth is `NOT_AVAILABLE_UNDER_CURRENT_GOVERNANCE`. No data was downloaded or newly authorized.

## Yearly entry-episode regime observations
| Year | Entries | Gate-on rate | Median close/MA20 | Median 20d momentum | Median MFE | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 37 | 100.00% | 1.89% | 2.42% | 3.35% | -7.71% |
| 2023 | 57 | 100.00% | 0.94% | 0.87% | 5.56% | -5.00% |
| 2024 | 38 | 100.00% | 3.05% | 3.79% | 6.42% | -6.16% |
| 2025 | 73 | 100.00% | 2.37% | 4.51% | 10.79% | -4.76% |

## Continuation
The frozen path observations show weaker early continuation and lower right-tail frequency in 2022–2023 than in 2024–2025. These are ex-post descriptive associations, not a classifier or trading rule.

## Persistence and whipsaw
`{"persistence": {"close_above_ma20": {"2022": {"median_run_length": 2.5, "p75": 9.5, "p90": 14.400000000000002}, "2023": {"median_run_length": 3.0, "p75": 5.5, "p90": 17.5}, "2024": {"median_run_length": 2, "p75": 9.0, "p90": 21.600000000000005}, "2025": {"median_run_length": 8, "p75": 15.0, "p90": 21.799999999999997}}, "ma20_above_ma60": {"2022": {"median_run_length": 25, "p75": 41.0, "p90": 50.6}, "2023": {"median_run_length": 16.0, "p75": 25.75, "p90": 34.300000000000004}, "2024": {"median_run_length": 34, "p75": 47.5, "p90": 55.6}, "2025": {"median_run_length": 18.5, "p75": 55.25, "p90": 95.30000000000001}}, "return20_positive": {"2022": {"median_run_length": 2, "p75": 8.0, "p90": 17.0}, "2023": {"median_run_length": 3, "p75": 7.0, "p90": 18.800000000000004}, "2024": {"median_run_length": 3, "p75": 8.0, "p90": 23.200000000000006}, "2025": {"median_run_length": 6.0, "p75": 24.5, "p90": 35.499999999999986}}}, "whipsaw": {"close_above_ma20": {"2022": {"state_flip_count": 28, "flips_per_100_days": 11.570247933884298}, "2023": {"state_flip_count": 31, "flips_per_100_days": 12.8099173553719}, "2024": {"state_flip_count": 26, "flips_per_100_days": 10.743801652892563}, "2025": {"state_flip_count": 29, "flips_per_100_days": 11.934156378600823}}, "ma20_above_ma60": {"2022": {"state_flip_count": 5, "flips_per_100_days": 2.066115702479339}, "2023": {"state_flip_count": 8, "flips_per_100_days": 3.3057851239669422}, "2024": {"state_flip_count": 5, "flips_per_100_days": 2.066115702479339}, "2025": {"state_flip_count": 6, "flips_per_100_days": 2.4691358024691357}}, "return20_positive": {"2022": {"state_flip_count": 22, "flips_per_100_days": 9.090909090909092}, "2023": {"state_flip_count": 26, "flips_per_100_days": 10.743801652892563}, "2024": {"state_flip_count": 26, "flips_per_100_days": 10.743801652892563}, "2025": {"state_flip_count": 19, "flips_per_100_days": 7.818930041152264}}}}`

## Findings
Trend-level and momentum families show the clearest descriptive separation, but market-gate state alone is not sufficient to explain the drift. Breadth is unavailable under current governance. Classification: **PARTIALLY_SUPPORTED**, evidence **MODERATE**; strongest family **MIXED**.

## Governance and next step
2022–2023 is consumed OOS and was not used to create a new strategy. Candidate families for Phase 10B are descriptive only: trend level, trend slope, and index momentum; no thresholds are proposed. Next direction: **MORE_REGIME_DIAGNOSTICS_REQUIRED**.
