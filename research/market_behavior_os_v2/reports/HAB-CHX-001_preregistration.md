# HAB-CHX-001 preregistration

Status: `FROZEN_BEFORE_MARKET_STATE_OUTCOME_JOIN`.

Frozen spec SHA-256:
`c17f8ea89cee61dc1ede89722bde38d0710c2a254b15e972fb19bd9664305a38`.

HAB-CHX-001 asks whether two already-frozen, strategy-independent market
coordinates describe CHINEXT V1's observed opportunity process or completed-
cycle payoff shape. Coordinate A is `sz399006` 60-session log direction.
Coordinate B is CHINEXT-board/ALL_STATUS 60-session net new-high/new-low
discovery. No third mechanism, minute state, optimized cutoff, or alternative
index/view may enter the primary experiment.

The breadth coordinate is not the old CHINEXT H-004 composite. H-004 used
breadth above MA20, positive 20-session return, and their change among strategy
entry dates. HAB-CHX-001 uses the separately constructed and portability-tested
new-high/new-low discovery fraction on every governed market date.

## Frozen population and semantics

The common valid market panel has 1,337 dates from 2018-07-03 through
2023-12-29. Before any payoff join, the exact frozen event ledgers contain 819
evaluated events, 638 admissible candidates, and 280 selected admissions inside
that window. All selected additions reconcile to same-date evaluated events.

Market state is formed at the completed signal-date close and can apply only to
a later execution. Missing state, unknown lineage, a same-date fill, an input
hash mismatch, or an unreconciled selected admission fails closed. The market
panels end in 2023, so 2024-2025 is excluded rather than proxied or backfilled.

An evaluated opportunity is an `ENTRY_SIGNAL_EVALUATED` event. An admissible
candidate additionally passes frozen MINVOL and has a non-null RS record. A
selected admission is a same-date desired-set addition. Calendar-day counts
include all zero-event state dates. A zero is the observed strategy process, not
pure latent-pattern incidence, because the engine's market-exit branch can
suppress entry evaluation.

## Frozen analyses

Absolute continuous coordinates are primary. Causal PIT and breadth-relative
coordinates are secondary diagnostics. The analysis reports univariate and
partial-rank associations, deterministic signal-date cluster bootstrap
intervals, early/late and yearly stability, leave-one-year-out sign counts, and
sample-identical `BASELINE`, `A`, `B`, and `A+B` nested models. Fixed sign cells
are coarse economic diagnostics only; zero is not advertised as a validated
habitat boundary.

Right-tail, opportunity/conversion, positive-PnL concentration, false-breakout,
and severe-loss outcomes use the already-frozen CHINEXT definitions. All
2018-2023 outcomes are consumed, so even a passed association gate remains
exploratory and cannot authorize a gate, veto, exposure overlay, candidate
strategy, or archetype.
