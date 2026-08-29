# ChinNext V1 formal PIT-universe validation

## Decision

**PIT_RESULT: BLOCKED**

The bounded date-effective universe candidate was successfully materialized and
technically reconciled, but it is not authorized for a formal strategy replay.
`configs/data_asset_registry.json` still classifies QD-007 as `DISCOVERY_ONLY` and
explicitly blocks universe construction, states, signals, and backtests. BaoStock's
historical security responses also expose no record-level historical `available_at`
or revision lineage. The repository's input-governance and fail-closed rules therefore
stop this task before signal generation. No current-survivor fallback was used.

This is a governance/lineage block, not a failed technical set reconciliation.

## Frozen scope

- Repository: `/Users/linmei/Documents/CY-supermind-v6`
- Branch: `research/chinext-v1`
- HEAD: `7ba9b09564df9510432bc5cc60e339aba64acb68`
- Date range: `2024-01-02 .. 2025-12-31`
- Strategy: `research/chinext_v1/strategy/chinext_v1_exploratory.py`
- Strategy SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Strategy modified: **NO**

The market gate, B60, FULL40, MINVOL, shadow breakout-volume diagnostic,
20/50/30 RS, ten 10% positions, SET_CHANGE_ONLY, NO_REPLACEMENT, MA30x2,
T+1, and close-to-next-open execution semantics were not changed or run.

## Bounded PIT-B candidate build

The builder used the Mac's existing local assets first:

- exact `GEM / SZ` identity from the local SZSE security master;
- the local exchange trade calendar;
- registered CY-006 for historical ST/trading-state/data-gap audit;
- one BaoStock 0.9.10 basic-security query plus only the five required historical
  snapshot queries. No full-market price download and no 485-day network crawl was
  performed.

The derived membership is inclusive over effective IPO/out dates and explicit
exchange sessions. It does not read
`chinext_current_survivor_universe.json`. The daily machine artifact remains under
the git-ignored `research/chinext_v1/data/pit_2024_2025/` directory.

| Build metric | Result |
|---|---:|
| Date count | 485 |
| Daily membership rows | 661,802 |
| Unique symbols in interval | 1,404 |
| Accepted exact GEM identities | 1,440 / 1,440 |
| Average daily universe | 1,364.5402 |
| Minimum daily universe | 1,333 |
| Maximum daily universe | 1,393 |
| Daily membership SHA256 | `9a6a0a071916b2af99a0f3f16b887672716b78428d28b4368f09bdd32d208c3d` |

The complete source hashes, request parameters, CY-006 input identity, artifact
hashes, row counts, and validation cases are frozen in
`chinext_v1_pit_master_manifest.json`.

## Required date validation

| Trade date | Derived interval set | BaoStock exact-board snapshot | Difference |
|---|---:|---:|---:|
| 2024-01-02 | 1,333 | 1,333 | 0 |
| 2024-06-28 | 1,348 | 1,348 | 0 |
| 2025-01-02 | 1,365 | 1,365 | 0 |
| 2025-06-30 | 1,382 | 1,382 | 0 |
| 2025-12-31 | 1,393 | 1,393 | 0 |

All five dates are exact symbol-set matches, not just equal counts.

| Case | Evidence | Result |
|---|---|---|
| A. Future listing absent | `301173.SZ` has zero pre-2025 membership rows | PASS |
| B. 179 sessions fails | `301429.SZ`, 2024-01-08, age 179 | PASS |
| C. Exactly 180 passes | `301429.SZ`, 2024-01-09, age 180 | PASS |
| D. Historical ST excluded by eligibility contract | CY-006 has 15,308 in-universe `is_st=true` rows; example `300010.SZ` on 2024-03-19 | PASS |
| E. Suspension/not-tradable excluded | CY-006 has 5,191 rows; example `300108.SZ` on 2024-03-19 | PASS |
| F. Delisted history retained | `300282.SZ`: 131 rows retained through its 2024-07-18 out date | PASS |
| G. Current-survivor absent | Builder has no current-survivor manifest input; enforced by test | PASS |

Four membership rows have no matching CY-006 row. A future authorized replay must
exclude those rows explicitly; they were counted, not backfilled.

## Why the formal replay did not run

| Gate | Evidence | Status |
|---|---|---|
| Bounded machine materialization | 485 dates, immutable local artifacts and digests | PASS |
| Listing/out interval audit | 1,440 identities, no missing basic/list date or invalid interval | PASS |
| Five-date historical set audit | 5/5 exact set matches | PASS |
| Required A-G behavior | all cases pass | PASS |
| Provider historical `available_at` / revision lineage | unavailable | BLOCKED |
| Registry authorization for universe/backtest | QD-007 remains `DISCOVERY_ONLY`; blocked uses are explicit | BLOCKED |

Creating a research-local manifest cannot silently override the central registry.
Doing so would weaken the repository's data-asset contract simply to obtain a return
number. Consequently, the PIT engine was not wired, the 10bps + 5bps sell-stamp cost
path was not computed, and all PIT performance/concentration metrics are `null`.

## Current-survivor comparator versus PIT

The left column is copied from the already-frozen exploratory reports. It was not
used for PIT membership. The right column is intentionally unavailable.

| Metric | Current-survivor | PIT |
|---|---:|---:|
| Universe size | 1,398 current survivors | BLOCKED |
| Entry candidates | 1,175 | BLOCKED |
| Round trips | 111 | BLOCKED |
| Average holdings | 4.0515 | BLOCKED |
| Average invested ratio | 40.3915% | BLOCKED |
| Total return, 10bps/side | 105.2422% | BLOCKED |
| Annualized return | 43.6891% | BLOCKED |
| Max drawdown | -26.2272% | BLOCKED |
| Win rate | 44.1441% | BLOCKED |
| Median trade | -1.0750% | BLOCKED |
| Top10 concentration | 62.3049% | BLOCKED |
| Top20 concentration | 84.2544% | BLOCKED |
| Return ex best10 | 3.6092% | BLOCKED |
| Return ex best20 | -32.1953% | BLOCKED |
| 2024 return | 49.0494% | BLOCKED |
| 2025 return | 37.7008% | BLOCKED |

Therefore this task cannot answer whether the current-survivor winner concentration
persists under a formally authorized PIT universe. Reporting a number would be a
silent governance fallback, not a robustness result.

## Tests

Command:

```text
research/chinext_v1/.venv/bin/python -m pytest -q research/chinext_v1/tests/
```

Result: **63 passed**. New tests cover future-listing exclusion, inclusive out-date
history, the 179/180-session boundary, and absence of the current-survivor manifest
from the PIT builder.

## Recommended next step

Create an explicit registry revision that either activates this exact bounded
artifact for PIT-B research or supplies a registered replacement with historical
`available_at`/revision semantics. Bind the exact manifest and hashes at runtime.
Only after that gate passes should the frozen strategy run once on this artifact;
no parameter changes or re-materialization are needed.
