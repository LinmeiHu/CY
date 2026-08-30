# Original-breakout lineage handoff

## Current status

Independent program initialized at autonomous branch start HEAD
`5309f2ef8a5ee6a57c7b63934acff77897faf1b3`. No outcome reveal has occurred in
this new program. CY-011 remains locked and unopened. EXP-OBL-003 has frozen
`LINEAGE-OBL-003-4193834A6A3A39BF` after two byte-identical full runs.

## Canonical original V1 breakout

At completed close `t`, `close_t` must strictly exceed the maximum of the prior
60 completed closes. FULL40 uses only prior 40 closes plus prior volatility
history; MINVOL uses only t-30..t-1. Own MA20, basic eligibility/liquidity,
market 399102 MA20 permission, cross-sectional RS ranking, portfolio capacity,
and no-replacement state also apply. Breakout-volume ratio is shadow-only. The
first executable buy is a later valid open, normally T+1.

## Available data

Registered CY-006 daily and QD-004/CY-008 minute PIT-B assets cover the historical
event range. Exact one-minute OHLCV/amount and deterministic five-minute/VWAP
features are feasible. Order books, ticks, bid/ask, and participant identity are
not available. Full signal-session features are available at 15:30 and can only
inform T+1 or later.

## Active experiment

EXP-OBL-001 is invalid due only to a one-character holdout-membership hash typo;
it stopped before reading a data row and produced no output. EXP-OBL-002 is the
clean identity with unchanged science and corrected binding. OBL-002 passed all
outcome-blind construction checks except the minimum-two-per-lineage/year gate:
2018 has only 11 events and split 1/4/3/3. It wrote no output. EXP-OBL-003 keeps
the exact taxonomy/assignments and changes only this gate to minimum one, testing
presence in every year. The runner projects only identity columns from the
accepted trade source; its explicit forbidden-column set blocks every future
outcome.

EXP-OBL-003 passes all construction gates. It covers 399 events, has lineage
counts 92/112/96/99, all four IDs in every year and block, 84.46% exact neighbor
agreement, 31,920 action-safe daily rows, 96,159 exact minute rows, and zero
forbidden outcome columns. H-OBL-002 decision: `FREEZE_LINEAGE`.

## Current frontier

Commit the frozen assignment and preregister EXP-OBL-004 as a separate outcome
reveal. Primary outcomes, contrasts, controls, LOYO/blocks, right-tail and
concentration attacks, and decision gates must be fixed before the first join.
No assignment, class label, or threshold may change afterward.

## Governance

H-004 remains prospective-validation pending; H-023 preserved; H-024/H-025
rejected; CBC-001/002 invalid and CBC-003 valid. Canonical V1 is unchanged. No
candidate rule exists. `CANDIDATE_READY_FOR_CY011: NO`.
