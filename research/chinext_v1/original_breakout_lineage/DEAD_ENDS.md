# Original-breakout lineage dead ends

## D-OBL-001 — historical order-book/participant-intent lineage

The registered asset inventory marks historical full-depth queues and
tick-by-tick orders unavailable. One-minute bars cannot reconstruct queue
priority, cancellations, hidden liquidity, or participant identity. Absorption
may be studied only as an explicitly limited OHLCV impact/recovery proxy.

Decision: `BLOCKED_DATA_GAP`; do not fabricate or silently download a dataset.

## D-OBL-002 — outcome-guided lineage construction

Any taxonomy chosen by future return, MFE, false-breakout status, winner class,
or exit outcome is forbidden by contract. It is not a fallback if an
outcome-blind taxonomy fails.

Decision: `REJECTED_BY_GOVERNANCE`.
