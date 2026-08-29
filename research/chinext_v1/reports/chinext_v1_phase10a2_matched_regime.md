# ChinNext V1 Phase 10A2 — within-year matched regime diagnostics

FORMAL_REPLAY_EXECUTIONS: `0`; NEW_TRADES: `0`; NEW_NAV: `0`; PIT_REBUILT: `NO`.
PHASE10A2_SPEC_SHA256: `9c79b348dc60cd9ec43e8199908a84a8aff90765047978da7f5cb97e567e0b83`

## Temporal matching
- RIGHT_TAIL_20_TOTAL: `42`
- TEMPORAL_MATCHED_COUNT: `33`
- TEMPORAL_MATCH_RATE: `78.57%`
- MEDIAN_MATCH_DISTANCE_DAYS: `1`
- Matching is same-year, nearest date within 30 calendar days, no replacement; ties use symbol then frozen episode id.

## Within-year counts
| Year | Right-tail 20 | Non-right-tail 20 | Right-tail 50 | Non-right-tail 50 |
|---:|---:|---:|---:|---:|
| 2022 | 2 | 35 | 0 | 37 |
| 2023 | 9 | 48 | 3 | 54 |
| 2024 | 11 | 27 | 9 | 29 |
| 2025 | 20 | 53 | 6 | 67 |

## Findings
Within-year and temporal-matched comparisons provide partial, non-uniform support for trend-level and momentum separation. Quarter-blocked and month-blocked evidence is mixed; no threshold or admission rule is proposed.

2024-09 is a descriptive high-trend reference only; it is not converted into a rule. 2022 loser feature distributions overlap materially with 2024–2025 right-tail entries, so a single feature is unlikely to be sufficient.

Decision: **DOES_REGIME_SIGNAL_SURVIVE_WITHIN_PERIOD_CONTROLS = PARTIALLY**; evidence **MODERATE**. Candidate feature families for a future experiment: none selected in this phase. Next direction: **MORE_REGIME_DIAGNOSTICS_REQUIRED**.

2022–2023 remains consumed OOS and cannot be used as untouched OOS for future selection.
