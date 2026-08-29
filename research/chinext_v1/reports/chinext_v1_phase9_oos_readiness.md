# ChinNext V1 Phase 9 OOS readiness

## Decision

`PHASE9_RESULT = BLOCKED_DATA_GOVERNANCE`

No Phase 9 replay was run. The Phase 8 winner-hold mechanism remains frozen at
20 trading sessions and +20% current return. No 2024–2025 experiment, threshold
search, universe substitution, or new download was performed.

## Available OOS candidates (read-only inventory audit)

| Candidate range | Local/registered evidence | What is available | Why it is not a legal Phase 9 replay |
|---|---|---|---|
| 2018-01-01 .. 2026-08-12 | CY-003/CY-006 daily PIT-B and CY-008 minute PIT-B registry entries | Historical daily/minute tables, trading-state fields, and calendar coverage | No authorized ChinNext V1 date-varying universe artifact outside CY-027; QD-007 remains `DISCOVERY_ONLY` and blocks universe construction, states, signals, and backtests |
| 2020-01-02 .. 2023-12-29 | CY-019/CY-020 | Dynamic main-board/ChiNext feature and lineage inventory | Registry scope is MARKUP_RETEST discovery/one-time 2023 validation; use outside that protocol is blocked |
| 2026-01-05 .. 2026-08-24 | CY-024/CY-025 and CY-001 fixture | Later daily/minute files exist locally | CY-024/CY-025 explicitly prohibit use by completed/frozen prior protocols; CY-001 is `QA_ONLY` and cannot support research conclusions |
| 2024-01-02 .. 2025-12-31 | CY-027 + `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1` | The only bounded ChinNext V1 PIT-B artifact used in Phases 1–8 | This is the already-used development interval, not OOS |

The technically most natural candidate would be 2022–2023, because it is
outside the Phase 1–8 evaluation interval. It is not a recommended executable
range: the registered CY-019/CY-020 inventory is authorized for a different
MARKUP_RETEST protocol, not this frozen ChinNext V1 mechanism.

## Required gate audit

| Requirement | Result | Evidence |
|---|---|---|
| Point-in-Time ChinNext universe for an OOS range | Missing | CY-027 is bounded to 2024-01-02..2025-12-31; QD-007 is `DISCOVERY_ONLY` |
| Listing history and historical membership | Missing for this protocol | Existing 2024–2025 artifact is the only bounded ChinNext authorization |
| Historical ST/risk and suspension/tradability states | Data exists in CY-003/CY-006, but cannot repair the missing authorized universe | Registry asset scopes and fail-closed rules |
| Authorized historical prices/volume/turnover | Partially available | CY-003/CY-006 coverage is registered, but no exact Phase 9 input snapshot/authorization |
| Trade calendar | Available | Local registered calendar covers 1990-12-19..2026-12-31 |
| No current-survivor fallback | Required and preserved | Phase 8/registry contract forbids fallback |
| Exact central authorization for OOS purpose/date range | Missing | Only `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1` exists, scoped to 2024–2025 |
| 120-day warmup | Technically plausible from daily tables, not sufficient to pass the universe/authorization gates | CY-003/CY-006 start in 2018 |

## Governance blockers

1. The sole ChinNext V1 bounded authorization is explicitly limited to
   `2024-01-02 .. 2025-12-31`, the Phase 1–8 interval.
2. QD-007 has no immutable historical security-master snapshots and is
   explicitly blocked for universe construction, states, signals, and
   backtests.
3. CY-019/CY-020 and CY-024/CY-025 have other protocol scopes and explicitly
   block use by a completed/frozen prior protocol or unrelated research.

## Data blockers

An OOS run cannot prove the required date-varying ChinNext membership, listing
age, historical risk-warning state, and tradability state under one authorized
input manifest. Reusing the current-survivor list or silently extending the
2024–2025 authorization would violate the Phase 9 contract.

## Minimal next action

Create a new append-only, centrally authorized ChinNext PIT-B artifact and
manifest for a pre-registered OOS range (including membership/listing/ST/
tradability, prices/volume/turnover, calendar, warmup, and exact hashes). Then
freeze an OOS spec before any result and run exactly `O0` followed by `O1` once
each. Until that authorization exists, Phase 9 remains blocked and no replay is
permitted.
