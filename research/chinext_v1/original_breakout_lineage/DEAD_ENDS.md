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

## D-OBL-004 — fixed-width repeated resistance-test episodes

The 2% episode count has strong variation but fails the preregistered neighboring-
definition gate: rho is 0.604 against the 1% definition and 0.713 against 3%,
while both were required to reach 0.65. The feature is therefore too dependent
on one arbitrary zone width for outcome testing.

No outcome was joined. Do not choose 3% after observing its higher agreement or
search other widths. Decision: `REJECTED_BEFORE_OUTCOME`.

## D-OBL-005 — single-session prebreakout positioning

The exact T-1 log distance to the canonical resistance reconstructed all 399
events and reconciled exactly, but it was not a stable formation state across
the fixed temporal neighbors. T-1/T-3 rho was 0.421 and T-1/T-5 rho was 0.309,
below the preregistered 0.60 requirement for both.

No outcome was joined and no feature artifact was written. Do not weaken the
gate, select one temporal horizon, search distance thresholds, or use this as a
retrospective entry rule. Decision: `REJECTED_BEFORE_OUTCOME`.
