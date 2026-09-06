# Phase 2B — Candidate-Pool Selection Audit

OC-EXP-P2-002: **PASS**. This is a fixed-horizon oracle diagnostic, not a replacement-entry replay or NAV.

## Lineage and coverage

| Block | Final candidates | Selected entries | Candidate days |
|---|---:|---:|---:|
| EXTENDED_2018_2021 | 380 | 194 | 208 |
| HOLDOUT_O0_2022_2023 | 266 | 94 | 106 |
| DEVELOPMENT_2024_2025 | 1175 | 121 | 159 |

Fixed-horizon coverage: 1816/1,821 at 5 sessions, 1816/1,821 at 10, and 1812/1,821 at 20.

## Selected versus unselected

| Group | N | Covered20 | Median MFE20 | Opp20 | Opp50 | Median close20 | Close20 >=20% |
|---|---:|---:|---:|---:|---:|---:|---:|
| selected | 409 | 409 | 10.08% | 25.92% | 7.09% | 0.77% | 13.69% |
| unselected | 1412 | 1403 | 9.55% | 23.31% | 4.13% | 0.76% | 10.19% |

## Same-day ranking ceiling

Across `259` selection days, only `30` contain an executable, covered alternative candidate. On those competitive days, authoritative selection includes the ex-post best-MFE20 candidate on `43.33%` of days and at least one ex-post top-3 candidate on `70.00%`. Median best-candidate MFE20 regret is `3.07%`. The all-day best-capture rate is `93.44%` but is mechanically inflated by 229 days with no alternative.

Within days containing both selected and unselected candidates, selected observations have mean day-centered MFE20 `3.19%` versus `-1.02%` for unselected observations.

Frozen RS score versus candidate MFE20 has breadth/year-controlled rho `0.047`, yearly signs `4+/4-`, and LOYO `8+/0-`.

Unselected outcomes assume a next-session executable open and a fixed 20-session hold. Best-candidate capture/regret uses hindsight and ignores capacity, portfolio feedback, and authoritative exit logic; it cannot authorize a stock-selection rule.
