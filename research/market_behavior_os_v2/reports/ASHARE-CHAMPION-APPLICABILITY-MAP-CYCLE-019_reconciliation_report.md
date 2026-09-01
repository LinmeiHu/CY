# Cycle 019 — revised-scope applicability-map reconciliation

## Scientific provenance

The revised user contract arrived after the original Cycle-019 outcomes had already been inspected and committed. This document is therefore a post-outcome scope reconciliation, not a new preregistration or independent experiment. The original frozen spec and evidence remain immutable and auditable.

## Executive conclusion

The Champion's habitat is partially identifiable ex ante, but not deployment-grade.

Final revised classification: `PARTIALLY_IDENTIFIABLE_HABITAT`.

Absolute market state matters most; lower stock-sign synchronization adds weaker repeated information. The map partly distinguishes 2022-like synchronized weakness from 2023-like structural opportunity. Relative Alpha survives on negative absolute cohort dates. No deployment experiment is scientifically earned because 2018 is not captured by the same adverse structure.

## Market-state definitions

| Dimension | Exact causal definition | Lookback / timing | Bucketing | Coverage |
|---|---|---|---|---:|
| ABSOLUTE_MARKET_STATE | compound the daily cross-sectional median PIT-valid stock step return over the 20 completed sessions ending at the decision close | 20 completed sessions at frozen weekly close | Expanding prior-only terciles after 20 prior observations | 263 dates |
| CROSS_SECTIONAL_DISPERSION | P90 minus P10 of PIT-valid individual-stock compounded returns over the same 20 completed sessions ending at the decision close | 20 completed sessions at frozen weekly close | Expanding prior-only terciles after 20 prior observations | 263 dates |
| INDUSTRY_PERSISTENCE | Spearman correlation of PIT-industry 20-session return ranks between the current and immediately preceding scheduled weekly observation | 20 completed sessions at frozen weekly close | Expanding prior-only terciles after 20 prior observations | 263 dates |
| SYNCHRONIZATION | absolute sign imbalance abs(2 * fraction of PIT-valid stock 20-session returns above zero - 1) | 20 completed sessions at frozen weekly close | Expanding prior-only terciles after 20 prior observations | 263 dates |

## Single-dimension maps

| Dimension | LOW / MEDIUM / HIGH dates | LOW / MEDIUM / HIGH payoff | Early / late favorable spread | Classification |
|---|---:|---:|---:|---|
| ABSOLUTE_MARKET_STATE | 74 / 96 / 93 | 0.29% / 2.27% / 1.61% | 1.52% / 1.19% | `STRONG_APPLICABILITY_INFORMATION` |
| CROSS_SECTIONAL_DISPERSION | 82 / 66 / 115 | 1.47% / 1.16% / 1.67% | 1.47% / -1.04% | `CHRONOLOGICALLY_UNSTABLE` |
| SYNCHRONIZATION | 109 / 87 / 67 | 2.16% / 0.96% / 1.05% | 1.02% / 1.31% | `WEAK_APPLICABILITY_INFORMATION` |
| INDUSTRY_PERSISTENCE | 84 / 89 / 90 | 1.74% / 1.60% / 1.12% | -0.21% / -1.00% | `NULL` |

Dispersion fails the revised coherence gate because its favorable spread reverses from early to late. Therefore Absolute State × Dispersion was not authorized for revised inference. The originally inspected Dispersion × Persistence map is likewise retired from revised inference.

## Authorized two-dimensional map — Absolute State × Synchronization

| Cell | Dates | Years | Early / late dates | Full / early / late payoff | Relative industry / broad | Support |
|---|---:|---:|---:|---:|---:|---|
| HIGH×HIGH | 33 | 6 | 20 / 13 | 1.86% / 2.05% / 1.57% | 1.31% / 7.02% | SUPPORTED |
| HIGH×LOW | 27 | 6 | 10 / 17 | 3.34% / 9.43% / -0.23% | 0.77% / 6.98% | SUPPORTED |
| HIGH×MEDIUM | 33 | 6 | 11 / 22 | -0.07% / 1.85% / -1.02% | 0.76% / 6.13% | SUPPORTED |
| LOW×HIGH | 33 | 5 | 13 / 20 | 0.49% / 1.76% / -0.34% | 1.19% / 4.87% | SUPPORTED |
| LOW×LOW | 6 | 3 | 2 / 4 | -9.08% / -10.21% / -8.52% | 3.02% / 1.75% | INSUFFICIENT_SUPPORT |
| LOW×MEDIUM | 35 | 6 | 18 / 17 | 1.72% / 4.03% / -0.73% | 2.49% / 5.49% | SUPPORTED |
| MEDIUM×HIGH | 1 | 1 | 1 / 0 | -7.02% / -7.02% / NA | 1.81% / -1.13% | INSUFFICIENT_SUPPORT |
| MEDIUM×LOW | 76 | 6 | 37 / 39 | 2.62% / 1.57% / 3.63% | 1.09% / 7.43% | SUPPORTED |
| MEDIUM×MEDIUM | 19 | 4 | 10 / 9 | 1.35% / -2.10% / 5.18% | 1.40% / 4.90% | SUPPORTED |

## 2022 versus 2023 and 2018 secondary check

- 2022: ABSOLUTE_MARKET_STATE=LOW, CROSS_SECTIONAL_DISPERSION=MEDIUM, SYNCHRONIZATION=HIGH, INDUSTRY_PERSISTENCE=HIGH; cohort payoff -0.14%; selected-industry d20 -1.56%; relative industry/broad 1.41%/5.79%.
- 2023: ABSOLUTE_MARKET_STATE=HIGH, CROSS_SECTIONAL_DISPERSION=LOW, SYNCHRONIZATION=LOW, INDUSTRY_PERSISTENCE=LOW; cohort payoff 1.36%; selected-industry d20 0.08%; relative industry/broad 1.29%/5.55%.
- 2018: ABSOLUTE_MARKET_STATE=MEDIUM, CROSS_SECTIONAL_DISPERSION=LOW, SYNCHRONIZATION=MEDIUM, INDUSTRY_PERSISTENCE=MEDIUM; cohort payoff -3.34%; selected-industry d20 -5.16%; relative industry/broad 1.82%/3.17%.

2022 spent materially more decisions in LOW absolute state and HIGH synchronization than 2023, which was dominated by HIGH absolute state and LOW synchronization. 2018 is only a July-onward partial period and is dominated by MEDIUM absolute state, so it does not validate a common adverse habitat.

## Absolute versus relative Champion value

Across 126 negative-payoff cohort dates, mean relative value remains 0.36% versus selected industries and 2.82% versus the broad proxy. Absolute long economics fail more often than relative selection Alpha.

## Applicability classification

`PARTIALLY_IDENTIFIABLE_HABITAT`.

## Next research implication

Do not run habitat-conditional deployment. Return capital to a second independent Alpha engine and strategy-diversification research. The frozen Dispersion Alpha question remains separate and unresolved.

No champion rule, exposure, filter, threshold, feature, or outcome was recomputed or changed. Post-2023 outcomes and CY-011 remain unread.
