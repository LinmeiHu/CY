# Phase 5 — Entry versus Exit Counterfactual Diagnostics

OC-EXP-P5-001: **PASS**. All ceilings are static, non-additive diagnostics; no new strategy replay was run.

## Conversion chain counts

| Stage | Count |
|---|---:|
| Completed trades | 399 |
| MFE >=20% opportunity | 84 |
| Opportunity20 -> terminal >=20% | 39 |
| Opportunity20 nonconversion | 45 |
| Nonconversion ending positive | 39 |
| Nonconversion ending nonpositive | 6 |
| MFE >=50% opportunity | 32 |
| Opportunity50 -> terminal >=20% | 30 |
| Opportunity50 -> terminal >=50% | 15 |

## Fixed-ledger ceilings (currency P&L or initial-capital oracle units)

| Diagnostic | Amount |
|---|---:|
| Actual realized P&L | 1,432,156 |
| Perfect terminal-sign selection | 1,946,013 |
| False-breakout avoidance | 1,809,331 |
| Severe-loss avoidance | 834,398 |
| Opportunity20 MFE-high giveback oracle | 2,869,832 |
| Opportunity20 peak-close giveback oracle | 2,242,643 |

Selection ceilings overlap. Exit ceilings use hindsight highs/peaks and initial capital, ignore portfolio vacancy/crowding and alternate-path feedback, and are not NAVs.

## Strict post-exit outcomes

Coverage is 399/399 at 5 sessions, 399/399 at 10, and 398/399 at 20. Exit-day close is excluded.

| Group | N | Covered20 | Median close20 | Median max-high20 | Max-high >=10% |
|---|---:|---:|---:|---:|---:|
| All | 399 | 398 | -0.92% | 9.96% | 50.00% |
| Opportunity20 | 84 | 84 | 4.42% | 16.74% | 69.05% |
| Opp20 nonconversion | 45 | 45 | 6.25% | 16.88% | 66.67% |
| False breakout | 213 | 212 | -1.87% | 8.18% | 45.28% |
| Severe loss | 44 | 44 | 0.25% | 8.33% | 43.18% |

## Frozen executable counterevidence

| Replay | Total-return delta | Year deltas | Interpretation |
|---|---:|---|---|
| E1_INDIVIDUAL_EXIT_DISABLED | -10.56 pp | 2024 3.05 pp; 2025 -9.71 pp | Mixed years; lower total return |
| E2_MARKET_EXIT_DISABLED | -13.52 pp | 2024 15.61 pp; 2025 -21.26 pp | Mixed years; lower total return |
| Winner hold, development | 9.51 pp | 2024 11.44 pp; 2025 -3.89 pp | Development-only promise |
| Winner hold, 2022-2023 OOS | -1.91 pp | negative_in_one_unchanged_in_one | NOT_SUPPORTED_OOS; only 2 activations |

Large hindsight giveback therefore establishes an economic ceiling, not a stable executable exit improvement. Post-exit maxima are future outcomes and cannot reverse the frozen OOS failure.
