# ChinNext V1 Phase 9C — zero-replay OOS failure attribution

No strategy replay, trade generation, NAV generation, PIT rebuild, parameter search, or counterfactual portfolio was performed.

- FORMAL_REPLAY_EXECUTIONS: `0`
- OOS_STATUS_AFTER_PHASE9B: `CONSUMED_FOR_DIAGNOSTIC_ANALYSIS`
- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Primary classification: **MIXED**; secondary: **RIGHT_TAIL_SCARCITY**; evidence: **MODERATE**

## Frozen year diagnostics
| Year | Trades | Win rate | Median return | Mean return | Avg winner | Avg loser | MFE>=20% | MFE>=50% | MFE>=100% | Median MFE | Median MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 37 | 13.5135% | -5.1183% | -4.8890% | 4.9635% | -6.4284% | 5.4054% | 0.0000% | 0.0000% | 3.3473% | -7.7070% |
| 2023 | 57 | 33.3333% | -2.0965% | 0.4439% | 9.9287% | -4.2985% | 15.7895% | 5.2632% | 0.0000% | 5.5587% | -5.0035% |
| 2024 | 38 | 31.5789% | -2.6202% | 15.1102% | 61.7423% | -6.4123% | 28.9474% | 23.6842% | 10.5263% | 6.4235% | -6.1554% |
| 2025 | 73 | 50.6849% | 0.4827% | 3.8901% | 14.8735% | -7.3985% | 27.3973% | 8.2192% | 1.3699% | 10.7931% | -4.7564% |

## Continuation diagnostics
| Year | Full 5d | Median 5d | Positive 5d | Full 10d | Median 10d | Positive 10d | Full 20d | Median 20d | Positive 20d |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 27 | -2.1119% | 29.6296% | 7 | -8.6661% | 28.5714% | 2 | 11.9066% | 100.0000% |
| 2023 | 41 | 1.5274% | 58.5366% | 31 | 3.4368% | 70.9677% | 10 | 2.5098% | 60.0000% |
| 2024 | 33 | -0.2423% | 48.4848% | 23 | 2.0063% | 65.2174% | 10 | 63.2540% | 100.0000% |
| 2025 | 68 | 0.7778% | 55.8824% | 50 | 0.8284% | 60.0000% | 25 | 4.4723% | 84.0000% |

## Expectancy and opportunity
- OOS expectancy: win rate `25.5319%`, average winner `8.8942%`, average loser `-5.2722%`, payoff ratio `1.6870`, profit factor `0.5784`, expectancy `-1.6552%`.
- Development expectancy: win rate `44.1441%`, average winner `26.3516%`, average loser `-6.9849%`, payoff ratio `3.7727`, profit factor `2.9816`, expectancy `7.7312%`.
- Candidate events / selected entries: OOS `266 / 94`; development `1175 / 121`.
- Exit-path canonical subtype split is PARTIAL_DESCRIPTIVE; individual and set-change reasons are combined in the frozen execution signal_reason.

## Interpretation
The OOS sample has a much lower win rate and weaker expectancy than development, with extreme right-tail concentration. Continuation diagnostics and MFE frequency should be read as descriptive path evidence, not causal counterfactuals. The low OOS exposure rules out simple over-exposure as the sole explanation; opportunity quality/regime dependence and right-tail scarcity jointly fit the frozen evidence.

## Governance
2022–2023 is now consumed for diagnostic analysis and must not be treated as untouched OOS for future selection. Any future strategy change requires a new date range and a new central authorization.
