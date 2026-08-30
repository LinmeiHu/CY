# Original-breakout lineage handoff

## Current status

Independent program initialized at autonomous branch start HEAD
`5309f2ef8a5ee6a57c7b63934acff77897faf1b3`. No outcome reveal has occurred in
this new program. CY-011 remains locked and unopened.

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

EXP-OBL-001 is frozen before outcome reveal. It creates four neutral quadrants of
base repair/compression and canonical prior-60 reference acceptance. The runner
projects only identity columns from the accepted trade source; its explicit
forbidden-column set blocks every future outcome.

## Current frontier

Execute and deterministically rerun EXP-OBL-001. If every frozen construction gate
passes, commit its `LINEAGE_FREEZE_ID`, then preregister EXP-OBL-002 outcome reveal.
If a gate fails, do not inspect outcomes; diagnose only the outcome-blind
construction and record REFINE or REJECT under a new identity if justified.

## Governance

H-004 remains prospective-validation pending; H-023 preserved; H-024/H-025
rejected; CBC-001/002 invalid and CBC-003 valid. Canonical V1 is unchanged. No
candidate rule exists. `CANDIDATE_READY_FOR_CY011: NO`.
