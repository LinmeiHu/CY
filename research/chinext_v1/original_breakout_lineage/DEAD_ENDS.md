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

## D-OBL-003 — 2x2 base-repair / signal-session acceptance lineage

The outcome-blind taxonomy is reproducible and stable as a classification, but
EXP-OBL-004 rejects its economic ordering. MFE and non-false-breakout raw rhos are
0.015 and 0.027; controlled rhos are 0.017 and 0.043; both earlier temporal
blocks contradict the positive development block. The five-minute/base neighbor
is approximately zero.

The acceptance axis is null. The base axis has a weak non-false-breakout
association but fails magnitude and block stability, so it cannot be promoted
post hoc. Do not relabel, merge, reweight, or threshold the four classes based on
revealed outcomes.

Decision: `REJECTED`; no entry, exit, size, overlay, or production rule.
