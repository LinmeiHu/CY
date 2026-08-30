# Original-breakout lineage research state

Updated 2026-08-30.

## Status

`PROGRAM_INITIALIZATION_AND_EVENT_RECONSTRUCTION`

The independent program is authorized. The dedicated worktree was validated at
HEAD `5309f2ef8a5ee6a57c7b63934acff77897faf1b3` with a clean tree before any
program write.

## Frozen background

- H-004: `PROSPECTIVE_VALIDATION_PENDING`.
- H-023: preserved exactly as authoritative historical state specifies.
- H-024: `REJECTED`.
- H-025: `REJECTED` by valid EXP-CBC-003.
- EXP-CBC-001/002: permanently `INVALID_ENGINEERING`.
- CY-011 2024-2026: `LOCKED_NOT_ACCESSED_BY_THIS_PROGRAM`.

## Canonical event finding

The original V1 breakout event is a completed official-close signal, not a
visually inferred lifecycle point. Its objective breakout reference is the
maximum of the prior 60 completed closes, and the signal close must strictly
exceed it. FULL40 and MINVOL use prior sessions only; signal-session breakout
volume is shadow diagnostic. Canonical selection also requires basic eligibility,
liquidity, own-MA, market permission, RS ranking, capacity, and no-replacement
portfolio state. An accepted buy first executes at a later valid open.

## Data finding

- CY-006 daily PIT-B: registered 2018-01-01..2026-08-12 with row-level lineage and
  hard-valid controls.
- QD-004: registered raw/unadjusted one-minute OHLCV/amount; exact frozen
  2018-2026 inventory.
- QD-005: deterministic session-aware 5-minute derivation only.
- CY-008: registered daily minute aggregates and six completed opening five-minute
  windows with exact inventory/audit.
- VWAP is reconstructable from CNY amount / share volume.
- Historical full-depth queues/tick-by-tick orders are registered unavailable.

The accepted 399 completed-cycle identity population spans 2018-2025 and has
one-to-one event keys. It is suitable for bounded PIT-B mechanism discovery but
is conditioned on completed accepted entries and is not strict archival PIT-A.

## Current scientific decision

`DEEPEN_EVENT_RECONSTRUCTION` — materialize a fresh outcome-blind formation frame
under a new program runner, freeze one small interpretable taxonomy without
reading outcomes, then preregister the reveal.

## Exact next action

Implement and test EXP-OBL-001 outcome-blind daily/intraday feature construction,
freeze its neutral lineage assignment under a new `LINEAGE_FREEZE_ID`, and only
then create a separate outcome-reveal experiment.
