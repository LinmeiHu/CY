# Strategy-independent market intraday sampling contract

## Purpose

AUDIT-MKT-MIN-001 asks only whether exact five-day minute descriptors can be
constructed on a bounded market-date sample without using CHINEXT events,
strategy membership, outcomes, or future information. It is not a representation
freeze and cannot establish usefulness.

## Frozen sample

- Years: 2018 through 2023.
- Anchor per year: the first exchange session on or after June 15.
- Predictor sessions: the five exchange sessions immediately before the anchor.
- Selection timestamp: completed Day -1 close.
- Views: ALL_A, SH_A, SZ_A, and CHINEXT_BOARD.
- Securities: ten per anchor/view, ordered by SHA-256 of
  `AUDIT-MKT-MIN-001|anchor|view|symbol`.
- Preselection uses CY-006 daily facts only and requires all five sessions to be
  hard-valid, PIT-valid, active/current-data-tradable, positive-volume rows.
  Minute completeness or descriptor values never enter selection.

View samples are retained as separate identities even if the same security also
appears in another view. The expected audit population is 240 trajectories and
1,200 trajectory-sessions. This fixed sample is a cross-year/view readiness
probe, not a claim of full-market distributional representativeness.

## Minute contract

The exact QD-004/CY-008 semantics in the accepted intraday data contract apply:
completed `bar_end_time`, a separate 09:30 auction row, continuous rows at
09:31..11:30 and 13:01..15:00, raw/unadjusted prices, shares/CNY units, hard
lunch boundary, and daily descriptor availability at 15:30 Asia/Shanghai.

Each sampled session must have 241 unique raw rows, one hard-valid CY-008 daily
row, six hard-valid opening five-minute windows, exact session grid, causal
daily context, and exact derived-five-minute volume/amount conservation. A
complete five-day trajectory is first available at Day -1 15:30 and cannot
justify any earlier or same-bar fill.

All 34 existing same-session dimensionless descriptor previews are constructed
only to test finite coverage and outcome-blind redundancy. Raw cross-day minute
prices are never compared. Corporate-action-aware multi-day price levels remain
deferred.

## Fail-closed boundary

Any inventory mismatch, missing selected session, invalid grid, time travel,
hard-valid failure, unit/reconciliation failure, nonfinite descriptor, or
volume/amount conservation failure rejects the audit. No replacement symbol,
narrower favorable sample, alternative vendor, imputation, or tolerance is
allowed.
