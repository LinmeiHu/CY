# Original-breakout lineage research state

Updated 2026-08-30.

## Status

`EXP_OBL_002_FROZEN_CLEAN_REEXECUTION`

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

## Active preregistration

EXP-OBL-001 is permanently invalid: it stopped at its first input-hash check due
to a one-character holdout-membership binding typo. No data row, feature,
lineage, or outcome was read or calculated; no output exists.

EXP-OBL-002 preserves every scientific definition, weight, 0.50 split, lineage
ID, gate, timing rule, and outcome prohibition. It changes only the corrected
membership hash plus fresh experiment, runner, and output identities.

## Current scientific decision

`EXECUTE_CLEAN_OUTCOME_BLIND_FREEZE` — materialize the frozen representation and accept
it only if coverage, class balance, every-year presence, neighboring assignment,
PIT, and deterministic rerun gates pass.

## Exact next action

Execute EXP-OBL-002 without any outcome access, verify byte-identical rerun, freeze
the assignment under a new `LINEAGE_FREEZE_ID`, and only then create a separate
outcome-reveal experiment.
