# ChinNext V1 Phase 12B — extended-history data foundation

Outcome-blind readiness only. This run performed zero strategy replay, zero full PIT materialization, and computed no strategy performance metrics.

## Frozen inputs

- Target: `2018-01-02 .. 2021-12-31` (973 exchange sessions)
- Required price warmup: 180 completed sessions; derived start `2017-04-12`
- Validation dates (frozen in Phase 12A): 2018-01-02, 2018-06-29, 2019-01-02, 2019-06-28, 2020-01-02, 2020-06-30, 2021-01-04, 2021-06-30
- Strategy SHA-256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- QD-007 remains `DISCOVERY_ONLY`.

## Governance decision

`PHASE12B_RESULT = PASS` means the audit and blocker evidence are complete. Readiness for materialization is **BLOCKED_DATA_GOVERNANCE**. No new bounded authorization was created because its required source facts are not yet authorized. QD-007 was not upgraded.

The existing CY-006 table is a frozen PIT-B daily source beginning at 2018-01-01 and has no 2017 partition. QD-001 has local raw daily bars reaching earlier years, but its causal corporate-action rebasing and CY-006-compatible adapter are not activated for this purpose. QD-004 has earlier raw 1-minute bars; using them as daily bars would be a silent semantic substitution and is prohibited.

The QD-007 discovery snapshots and the 2010–2017 bridge do not provide an immutable, authorized date-effective ChinNext universe with the required historical listing, out/delisting, ST/risk-warning, suspension, and non-survivor semantics. A current security master cannot fill this gap.

## Source matrix

The script records the complete candidate matrix in the JSON summary. All unknown required facts fail closed. Existing 2022–2025 PIT artifacts and their authorizations are not extended or rebuilt.

## Pilot and correctness

The eight frozen dates were not changed. Pilot materialization was **not run** because no authorized PIT universe and compatible warmup source passed the gate; each date is recorded as `BLOCKED_NO_AUTHORIZED_PIT_ARTIFACT`. Boundary, future-listing, non-survivor, ST, suspension, and overlap checks are therefore explicitly unavailable for 2018–2021 rather than inferred from current membership.

The 179/180 contract remains the frozen rule (`179` excluded, `180` included), but a 2018–2021 source-specific test is deferred until authorization exists.

## Readiness gates

- Extended universe: **NO**
- Price data: **PARTIAL** (2018–2021 CY-006 observations exist; 2017 compatible warmup is not activated)
- History window: **NO**
- Market anchor: **YES** (existing 399102.SZ coverage)
- Execution data: **PARTIAL**
- Corporate-action semantics: **YES** for the frozen CY-006 contract; warmup equivalence is not proven
- Governance: **NO**

`CAN_PROCEED_TO_FULL_2018_2021_PIT_MATERIALIZATION = NO` and `CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY = NO`.

Estimated full materialization size is approximately 1,070,300 membership rows / 3,161,896 bytes using the Phase 12A empirical estimate; no large build was started.

## Blockers and next action

1. Materialize and authorize an immutable QD-007-derived 2018–2021 date-effective universe, including historical non-survivor, ST, suspension, and out-date evidence.
2. Activate a daily 2017 warmup source with proven raw-price, causal corporate-action, volume/amount, symbol, and calendar equivalence to CY-006.
3. Create a new bounded data-foundation authorization tied to exact manifests and the eight dates.
4. Run Phase 12C full PIT materialization and correctness validation only after those gates; keep replay authorization separate.

No strategy parameters, frozen strategy source, existing PIT artifacts, or Phase 1–12A reports were modified.
