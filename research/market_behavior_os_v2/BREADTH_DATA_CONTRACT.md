# Strategy-independent breadth data contract

## Registered source

- Asset: `CY-006`, daily PIT-B causal research table v2.
- Source root:
  `/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily`.
- Manifest:
  `/Users/linmei/Documents/CY/data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json`.
- Manifest SHA-256:
  `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.
- Permitted construction partitions: 2018 through 2023 only. Files for 2024,
  2025, and 2026 are not read.
- PIT grade: bounded PIT-B; no strict archival PIT-A claim.

The runtime must verify the registry, manifest, and exact selected partition
hashes before construction.

## Timestamps and causality

- Observation timestamp: official daily `trade_date` bar.
- Decision timestamp: completed official close at 15:00 Asia/Shanghai.
- Required record rule: `available_at <= decision_at`.
- First possible action: a later causally valid session. This experiment creates
  no signal or action.
- `snapshot_id` and source lineage are preserved in daily audit output.
- No future observation enters a representation or PIT normalization.

## Strategy-independent denominator

History-coordinate validity requires the registered hard-valid, bar, trading-
state, corporate-action, market-rule, and historical-identity gates; finite
positive close; finite nonnegative volume/amount; nonblocking corporate action;
and completed-close availability.

A current security can contribute to breadth only when it is also trading and
currently data-tradable with positive volume. The primary denominator includes
ST securities; `NON_ST` is a fixed sensitivity denominator. There is no V1
membership, listing-age rule, liquidity threshold, ranking rule, or current-
survivor substitution.

All long-horizon concepts use one comparable core: 120 consecutive exchange
sessions with valid causal coordinate steps. A missing or invalid required row
invalidates every exact rolling window that touches it. It is never normalized,
clipped, tolerated, forward-filled, or replaced.

Minimum current counts are 1,000 for ALL_A, 400 for SH_A and SZ_A, and 200 for
CHINEXT_BOARD. Concept coverage must be at least 95% within the eligible view.

## Corporate-action price coordinate

For a valid visible supported action at `t`, the prior raw close is rebased as:

`(prior_close - cash_per_share) / share_multiplier`.

The coordinate step is `log(close_t / rebased_prior_close)`. A no-action step is
`log(close_t / prior_close)`. Nonzero rights participation, unavailable action
facts, nonpositive rebased price, blocking actions, calendar gaps, or unknown
lineage make the step missing and fail closed. The continuous coordinate is the
exponentiated cumulative sum of valid log steps; no future adjustment factor is
used.

## Forbidden inputs

- CHINEXT V1 membership, signals, admissions, trades, fills, returns, MFE, MAE,
  exits, durations, or outcome classes;
- SuperMind V6 outcomes;
- future returns or post-decision observations;
- current constituent lists or present-day survivors;
- unregistered index membership, industry fallback, market-cap, style, fund-flow,
  sentiment, or participant-identity data;
- CY-011.

## Fail-closed conditions

Stop or mark the affected representation missing on manifest mismatch,
duplicate symbol/date keys, post-2023 reads, time-travel lineage, invalid OHLC,
coordinate nonconservation, inadequate view size/feature coverage, inadequate
industry mapping, or noncausal historical normalization.
