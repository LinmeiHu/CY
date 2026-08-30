# AUDIT-ROSV2-M001 — five-day minute data audit

Decision: `PASS_FIVE_DAY_MINUTE_DATA_AND_DESCRIPTOR_FEASIBILITY`.

## Outcome-blind population

- canonical events: `399`;
- Day -5..Day -1 event-sessions: `1995`;
- distinct symbol/date source sessions: `1992`;
- raw rows after event mapping: `480795`;
- descriptor rows and fields: `1995` x `34`;
- outcome, return, P&L, MFE, MAE, exit, and holding fields read: `0`.

## Contract result

Every event has the exact five preceding exchange sessions. Every session has a separate 09:30 auction row plus 240 continuous rows at 09:31..11:30 and 13:01..15:00. All QD-004 files use raw/unadjusted 1m SZ semantics. CY-008 daily and opening-window rows pass the frozen hard-valid, session, unit, trading-rule, causal-input, volume, amount, and timestamp gates.

Maximum relative QD-004 versus CY-008 opening-window difference: `0`.
Maximum derived-5m volume/amount conservation difference: `0`.

## Corporate actions and execution

Prices remain raw/unadjusted and all preview descriptors are same-session dimensionless quantities. No raw price is compared across sessions. Cross-day price-level/support features remain deferred to an accepted action-safe daily coordinate. The complete Day -5..Day -1 trajectory is known after Day -1 at 15:30, strictly before the signal session; it can never justify an earlier or same-bar fill.

## Representation feasibility

The audit materializes interpretable daily descriptor previews for price path, VWAP, selling/buying pressure, volatility, and volume concentration. These are outcome-blind feasibility evidence, not frozen predictors. The recorded rank-correlation pairs must be used to compress redundant representations before any outcome reveal.

## Limitations

OHLCV bars do not reveal aggressor side, queue state, cancellations, hidden liquidity, absorption, or participant identity. Support/resistance progression that compares price levels across days requires a separate action-safe level contract. All history remains bounded PIT-B and outcome-consumed for later association.

## Next decision

If PASS, rank one minimal outcome-blind five-day representation freeze against the three-coordinate trend build. Do not combine or outcome-screen the 34 preview descriptors.
