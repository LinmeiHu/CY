# ChinNext V1 Phase 4 — exposure-matched decomposition

> Diagnostic counterfactual only. The A0 member-count schedule was frozen before
> matched results; no baseline symbol identity was copied and no parameter was searched.

## Frozen identity

- PHASE4_SPEC_SHA256: `6823ac96d9f93922e64f71e2b7dd0048ca522f7c280b9d4388534e8c77563509`
- PHASE4_SPEC_FROZEN_BEFORE_RESULTS: `YES`
- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- PIT_MANIFEST_DIGEST: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`
- NEW_FORMAL_REPLAY_EXECUTIONS: `2`
- FORMAL_ORDER: `M2 -> M3`
- PIT_REBUILT: `NO`

## Headline comparison

| Arm | Total return | Max DD | Trades | Avg holdings | Avg invested | Baseline Top20 | Return ex best20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| A0_BASELINE | 105.2422% | -26.2272% | 111 | 4.052 | 40.3915% | 20/20 | -32.1953% |
| A2_MINUS_B60_RAW | 42.7426% | -22.2107% | 239 | 5.474 | 54.3718% | 7/20 | -67.0186% |
| M2_MINUS_B60_BASELINE_CAPACITY | 47.6976% | -22.5782% | 129 | 4.049 | 40.2714% | 7/20 | -68.3298% |
| A3_MINUS_FULL40_RAW | 133.7522% | -32.2766% | 207 | 5.913 | 58.5199% | 1/20 | -72.2847% |
| M3_MINUS_FULL40_BASELINE_CAPACITY | 87.5642% | -25.8913% | 110 | 4.103 | 40.7200% | 0/20 | -94.6890% |

## Matched-arm uniform metrics

| Arm | Annualized | Win rate | Median trade | Mean trade | 2024 | 2025 | Top10 conc. | Top20 conc. | Return ex best10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M2_MINUS_B60_BASELINE_CAPACITY | 21.7269% | 37.9845% | -3.1920% | 4.0235% | 45.4959% | 1.5132% | 69.2124% | 90.5966% | -40.9431% |
| M3_MINUS_FULL40_BASELINE_CAPACITY | 37.3105% | 35.4545% | -6.2492% | 7.2567% | 56.6758% | 19.7148% | 58.4363% | 85.9851% | -36.2968% |

## Offline winner crowd-out

- B60/A2: captured `7/20`; direct finite-capacity crowd-out `12/13` missing episodes; outranked `5`; no vacancy from earlier extras `7`; path divergence `1`.
- FULL40/A3: captured `1/20`; direct finite-capacity crowd-out `19/19` missing episodes; outranked `10`; no vacancy from earlier extras `9`; path divergence `0`.

Each classification is backed by the persisted candidate evaluation, frozen RS rank,
desired-set transition, and earlier extra-entry lineage in the crowd-out CSV.

## Extra candidate quality

| Arm | Selected extras | Completed | Win rate | Median return | Mean return | Total P&L | Median holding sessions |
|---|---:|---:|---:|---:|---:|---:|---:|
| A2_MINUS_B60_RAW | 198 | 190 | 31.5789% | -2.2187% | 0.0652% | 3,637.84 | 4.0 |
| M2_MINUS_B60_BASELINE_CAPACITY | 71 | 67 | 38.8060% | -2.8412% | 2.1108% | 102,899.17 | 8 |
| A3_MINUS_FULL40_RAW | 215 | 205 | 35.1220% | -4.9943% | 3.3699% | 668,344.05 | 12 |
| M3_MINUS_FULL40_BASELINE_CAPACITY | 120 | 110 | 35.4545% | -6.2492% | 7.2567% | 685,673.70 | 14.0 |

MFE/MAE remains `UNRESOLVED_NOT_COMPUTED`; no new price-path attribution semantics
were introduced.

## Capacity-envelope fidelity

- M2 survivor-overflow days: `4`
- M3 survivor-overflow days: `28`
- Existing survivors were never force-sold to chase A0 realized exposure.
- Position sizing, exits, costs, PIT, RS ordering, and date range stayed frozen.

## Execution correctness

- Same-day fills across M2/M3: `0`
- Stale held valuations across M2/M3: `0`
- Phase 3 frozen input hashes unchanged: `YES`
- Transaction cost: fixed `10 bps/side`
- Current-survivor fallback: `NO`

## Interpretation

- B60 PRIMARY_ROLE: **SECURITY_SELECTION**
- B60 EVIDENCE_STRENGTH: **MODERATE**
- FULL40 PRIMARY_ROLE: **MIXED**
- FULL40 EVIDENCE_STRENGTH: **MODERATE**

These are sample-specific diagnostic results, not causal production claims.

## Phase 4 findings

- **B60:** Raw removal expanded trades by 128 and invested fraction by 13.9804pp. Capacity matching reduced those deltas to +18 trades and -0.1201pp, yet return remained 57.5446pp below A0, Top20 capture remained 7/20, and return-ex-best20 remained materially worse. This supports security-selection value beyond exposure control.
- **FULL40:** Raw removal's +28.5100pp return coincided with +96 trades and +18.1285pp invested fraction. At A0-like capacity the deltas became -1 trade and +0.3286pp exposure, while return became -17.6781pp versus A0 and drawdown converged to A0. However Top20 capture fell from 1/20 to 0/20 and return-ex-best20 worsened, supporting a mixed exposure-control and selection/crowd-out role.
- **Winner crowd-out:** Offline Phase 3 lineage attributes 12/13 missing A2 winners and all 19/19 missing A3 winners directly to finite-capacity crowd-out. Capacity matching did not restore them (M2 7/20; M3 0/20), because the matched arms still use their own expanded candidate sets and frozen RS ordering.
- **Extra candidates:** M2 completed extras had 38.8060% win rate, -2.8412% median return and +102,899.17 P&L. M3 completed extras had 35.4545% win rate, -6.2492% median return and +685,673.70 P&L. Positive means and P&L coexist with negative medians, showing right-skewed extra-candidate quality.
- **2024-09 cohort:** M2 and M3 each retained 10 September-entry completed cycles and 9/20 arm Top20 trades. Their cohort P&L was 671,437.76 and 854,430.77, representing 52.4272% and 40.3112% of positive P&L. Cohort dependence therefore persists; counterfactual portfolio return remains UNRESOLVED.

## September-2024 cohort

- M2 entry count / P&L: `10` / `671,437.76`
- M3 entry count / P&L: `10` / `854,430.77`
- Counterfactual portfolio return excluding the cohort remains `UNRESOLVED`.

## Next question — not run

Freeze a path-conditioned decomposition of the extra-entry cohorts themselves,
without changing B60/FULL40 thresholds or any exit rule.
