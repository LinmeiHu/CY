# Champion mid-rank concentration

Status: `SIMPLE_RULE_IMPROVES_BUT_TARGET_NOT_MET`.

This is a post-hoc development translation of Cycle-016's already observed ranks-3-to-5 payoff advantage, not independent confirmation.

## Frozen rule

On each exact Champion weekly signal, retain only emitted ranks 3, 4, and 5; split the unchanged one-quarter cohort capital equally, enter at the next legal open, and retain the exact 20-session lifecycle.

## Executable result

| Portfolio | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Trades | Positions | Industries | P10 capacity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline Top-10 | 122.43% | 16.34% | -25.77% | 0.731 | 0.634 | 14.13% | 2625 | 39.3 | 12.4 | CNY 111,124,306 |
| Ranks 3-5 | 234.79% | 25.71% | -26.03% | 0.958 | 0.988 | 13.96% | 788 | 11.8 | 5.3 | CNY 33,231,657 |

Delta: annualized +9.36%, maximum-drawdown quality -0.25%, Sharpe +0.226, severe-trade quality +0.17%.

User return-and-drawdown target met: `False`.

No alternative rank set, weight, horizon, filter, or rescue replay was run.
Post-2023 outcomes and CY-011 were not read.
