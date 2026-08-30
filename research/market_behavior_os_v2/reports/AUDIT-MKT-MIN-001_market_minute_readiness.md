# AUDIT-MKT-MIN-001 market-minute readiness

Decision: `PASS_STRATEGY_INDEPENDENT_MARKET_MINUTE_READINESS`.

## Population

- trajectories: 240
- five-day sessions: 1200
- raw mapped rows: 289200
- views: ALL_A, SH_A, SZ_A, CHINEXT_BOARD
- strategy membership, outcomes, returns, MFE, MAE, exits, and CY-011 read: **none**.

## Contract result

- maximum opening-window relative difference: `0.0`
- maximum derived-five-minute conservation difference: `0.0`
- flat sessions: 2; limit-up locked: 1; limit-down locked: 1.

Every selected trajectory has exact Day -5..Day -1 completed sessions. The complete trajectory is available only at Day -1 15:30 and cannot justify an earlier or same-bar fill.

## Interpretation

PASS establishes strategy-independent cross-year/view data and descriptor feasibility only. It does not freeze a minute representation, compare winners/losers, establish a mechanism, or imply a strategy archetype.

## Reproducibility

- spec SHA-256: `828df9fe6c498d4f0f073477ab22b5cb40e22191ed65b2fb44deaf2a88115566`
- sample SHA-256: `6cc2f9b692274a2dcb309f368f0efc710cec464d38fe77146e03197c595bf6e4`
- descriptors SHA-256: `9f177c29cb019cdbc667392fbf72db0ffb9e7fdb2d3d30bcfb8669888cc1d13c`
