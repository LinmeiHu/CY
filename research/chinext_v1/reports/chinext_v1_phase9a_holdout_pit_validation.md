# ChinNext V1 Phase 9A — 2022–2023 holdout PIT validation

## Frozen scope

- Purpose: `CHINEXT_V1_TEMPORAL_HOLDOUT_PIT_2022_2023`
- Calendar years: 2022–2023
- First trading date: `2022-01-04`
- Last trading date: `2023-12-29`
- Required warmup start: `2021-07-08` (120 exchange sessions before the first holdout session)
- Strategy/PnL/NAV replay executions: **0**
- Current-survivor membership input: **NO**
- Phase 1–8 selection contamination of this holdout: **NO**

The build reuses the existing `pit_universe.py` listing-age/effective-date
helpers, the local exact GEM security master, the previously captured local
BaoStock basic snapshot, the frozen quant exchange calendar, and registered
CY-006 daily PIT-B rows. It does not run B60, FULL40, MINVOL, RS, winner-hold,
portfolio, or return logic.

The Phase 1–8 frozen specs bind the evaluated strategy interval to
2024-01-02..2025-12-31. The Phase 8 winner mechanism is fixed at 20 sessions
and +20% in its pre-result spec; no 2022–2023 outcome was read to select those
values or any B60/FULL40/MINVOL/RS/exit arm. The holdout is therefore not used
to choose the mechanism being prepared for Phase 9B.

## Materialized artifact

| Field | Value |
|---|---:|
| Holdout dates | 484 |
| Unique symbols in membership | 1,350 |
| Membership rows | 591,299 |
| Average daily universe | 1,221.6921 |
| Minimum daily universe | 1,090 |
| Maximum daily universe | 1,333 |
| Future-listed exclusion rows | 0 |
| Historical non-survivor symbols | 41 |
| Fail-closed rows | 11,904 |
| 20-session liquidity windows missing/invalid | 8,492 |

The fail-closed rows are CY-006 rows with `hard_valid=false`; no invalid row is
silently promoted into an eligible pool. There were no missing daily rows,
missing `available_at`, or missing `snapshot_id` values in the joined holdout
membership rows. Historical ST rows (10,213) and suspended/untradable rows
(11,904) remain explicit state evidence for the downstream frozen universe
gates; they are not converted to false or silently removed from the PIT record.

## Fixed calendar-deterministic snapshot audits

| Audit date | Membership count | Sorted-symbol set SHA-256 |
|---|---:|---|
| 2022-01-04 | 1,090 | `c8fef6d6439ea6b3fd798e0282d8db725c412661132df2b0c910dc67a7b9aadb` |
| 2022-06-30 | 1,154 | `80b74860c2b2644ad8dbfa507051d1360b8e9829f0fd045eaa0c46ea48e3eae2` |
| 2023-01-03 | 1,232 | `c20381eb7959dbd43f3e0c6f95b3f18bd7d2a04c068c046ed3124b48d9f2debd` |
| 2023-06-30 | 1,282 | `68b7e6dccb140fab30e0d754286a09d60ba3faf1215afb65ed3c38397e0a49ed` |
| 2023-12-29 | 1,333 | `b637232bae219e0583e6dc0b563af78311b4fe4757623d1e13daa1283c9adba2` |

Two consecutive local materializations produced identical membership and
security-master Parquet hashes and an identical manifest after removing a
self-referential hash. No network refresh was used.

## Correctness gates

| Gate | Result | Evidence |
|---|---|---|
| Future-listed stock absent before listing | PASS | 300804.SZ has zero pre-listing membership rows |
| 179/180 listed-session boundary | PASS | 300967.SZ is 179 sessions on 2022-01-04 and 180 on 2022-01-05 |
| Historical ST/risk state preserved | PASS | CY-006 contains 10,213 `is_st=true` rows; state remains explicit |
| Historical suspension/tradability preserved | PASS | CY-006 contains 11,904 suspended/untradable rows; state remains explicit |
| Historical delisted securities retained | PASS | 17 symbols and 4,182 valid historical membership rows retained through their effective interval |
| Explicit exchange calendar | PASS | 8,797-session local calendar; 484 holdout sessions |
| Deterministic date-set reproducibility | PASS | two consecutive local builds byte-identical |
| Chronological membership interval continuity | PASS | all 1,350 symbols match their effective list/out interval on the explicit calendar |
| No current-survivor membership input | PASS | builder inputs are exact GEM master, effective basic snapshot, calendar, and CY-006 |
| 2024–2025 artifact unchanged | PASS | prior manifest SHA-256 remains `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`; daily/security hashes unchanged |

## PIT and lineage limitations

This is a bounded PIT-B reconstructed artifact. BaoStock supplier-level
record `available_at` and revision-vintage history are unavailable, so the
artifact does not claim strict archival PIT-A or vendor-level revision-aware
certification. CY-006 row-level `available_at`, `snapshot_id`, `hard_valid`,
trading-state, and market-data fields are preserved and fail closed.

## Authorization outcome

The PIT correctness gates pass. A new central registry asset (`CY-028`) and a
new bounded authorization are added only after this validation. The authorization
is limited to `research/chinext_v1`, this exact manifest/digest/date range, and
the two frozen Phase 9B arms (`O0_BASELINE`, `O1_WINNER_HOLD`). It does not
upgrade QD-007, reuse CY-019/CY-020 or CY-024/CY-025 authorizations, or permit
any replay in this Phase 9A task.
