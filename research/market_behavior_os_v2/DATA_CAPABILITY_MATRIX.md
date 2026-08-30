# Data capability matrix

| Scientific need | Governed asset | Current capability | Boundary |
|---|---|---|---|
| Strategy-independent daily state and eligibility | CY-006 | PASS, bounded PIT-B, immutable 2018-2026 inventory | Construction remains pre-2024; `available_at <= decision_at` and `hard_valid` required |
| Causal daily industry membership and stock/industry relative return | CY-006 | PASS for pre-2024 MKT-INDRS-001; 100% mapped coverage on valid output rows and exact other-member context | Source-notice date must be no later than trade date; five-member/80%/ten-industry gates and action-aware coordinates remain mandatory |
| Raw one-minute price/volume path | QD-004 | PASS CONDITIONAL, raw/unadjusted 1m bars, immutable target inventory | No record-level archival availability; completed-bar availability and frozen snapshot only |
| Minute causal daily/session gate | CY-008 daily | PASS, exact daily hard-valid/session/unit/reconciliation lineage | Must bind the matching CY-006/QD-004 snapshots; no hard-invalid state |
| Opening-window reconciliation | CY-008 execution_5m | PASS for six 5-minute opening windows | Execution rows do not represent the full intraday path |
| Exact market calendar | QD-002 calendar binding | PASS | Frozen exchange-session dates only |
| Same-session dimensionless descriptors | QD-004 + CY-008 | PASS on AUDIT-MKT-MIN-001; required-scale adapter pending | Available at session date 15:30; no same-bar use |
| Cross-day objective support/resistance | CY-006 causal action chain + QD-004/CY-008 raw minute path | TWO STABLE RECOVERY TRAJECTORY COORDINATES; COMMON PROCESS FAIL | Timing/activity endpoint rates pass shape/level/auction/generic controls, but direction and residual coupling fail; completion F arm is sparse. PIT historical/relative state and usefulness remain absent |
| Order-flow aggressor, queue, cancellation, hidden liquidity, participant identity | none | UNAVAILABLE | OHLCV/amount cannot support these claims |
| Historical constituent-index minute breadth | none | UNAVAILABLE | Current constituent lists may not substitute; use governed ALL_A/SH_A/SZ_A/CHINEXT_BOARD views |
| Strict archival PIT-A | none for the active minute source | UNAVAILABLE | All active minute conclusions remain bounded PIT-B |
| Whole-book semantic chip state | CY-011 | LOCKED/UNOPENED | Not required by the active frontier and must remain unopened |

The active minute question uses only CY-006, QD-004, CY-008, and the frozen
calendar. QD-006 alternatives remain QA-only and can never silently replace a
missing governed input.
