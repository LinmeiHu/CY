# Objective cross-day support-defense data contract

Frozen before MKT-SUPPORT-DATA-001 accesses new raw minute rows. This contract
asks whether an objectively defined prior daily price level and the current
minute path can be expressed in one causal corporate-action coordinate. It does
not construct or validate a support-defense representation.

## Bound sources and PIT grade

- CY-006 daily PIT-B v2 supplies raw daily OHLC, trading state, price limits,
  causal corporate-action facts, availability, snapshot identity, and hard-
  validity flags.
- QD-004 supplies raw/unadjusted one-minute OHLCV/amount with completed bar-end
  timestamps and exact frozen annual-file identities.
- CY-008 daily PIT-B v2 binds the raw minute session to the exact CY-006 daily
  snapshot and supplies session completeness, OHLC/unit/reconciliation, and
  15:30 availability gates.
- QD-010 is the frozen PIT-B corporate-action upstream. It is not archival PIT-A;
  late, incomplete, rights, blocking, conflicting, or unsupported actions fail
  closed.

No adjusted-price vendor field, present-day action history, strategy table,
fallback minute source, or post-2023 partition may enter.

## Causal action coordinate

For consecutive hard-valid daily rows of one security, define the prior-close
bridge on date t:

- no declared action: `bridge_close(t) = close(t-1)`;
- supported cash/share action known and effective by t:
  `bridge_close(t) = (close(t-1) - cash_per_share(t)) / share_multiplier(t)`.

The action step is valid only when `rights_ratio=0`, `share_multiplier>0`, the
bridge is positive, the action is nonblocking, and every corporate-action
availability/validity flag passes. Then

`step_log_return(t) = log(close(t) / bridge_close(t))`.

The arbitrary-base continuous coordinate is the cumulative exponential of
valid step log returns. Daily high and low are mapped by multiplying their raw
high/close and low/close ratios by the continuous close. Every required lookback
step must be valid; `coalesce`, interpolation, forward fill, future adjustment,
or chain repair is prohibited.

## Prior support levels

For audit only, define exact prior-low candidates from adjusted daily lows
through t-1:

- primary: previous 20 consecutive exchange sessions;
- fixed feasibility neighbors: previous 10 and 40 sessions.

The level is available at t-1 15:00 Asia/Shanghai. These horizons are not yet
accepted representations and no favorable one may replace another.

## Current minute coordinate

QD-004 must contain exactly 241 unique raw rows: a separate 09:30 auction row,
continuous rows 09:31..11:30 and 13:01..15:00, no lunch rows, `adjust=none`,
shares/CNY units, and no anomaly or duplicate.

The QD-004 completed-session close must exactly equal the causal CY-006 raw
close. The current action-aware scale is

`continuous_close(t) / raw_close(t)`.

Multiply every raw minute OHLC by this scale. The transformed 15:00 close must
equal the continuous daily close exactly. This uses the completed t close and
therefore makes any derived support-test descriptor available only at t 15:30.
It cannot be used at an earlier minute or to fill inside t.

## Limits, suspensions, and missing bars

Current sessions require hard-valid active/tradable CY-006 context, positive
volume, exact CY-006/CY-008 snapshot binding, and complete reconciled CY-008
minute context. Suspensions and missing/incomplete sessions fail closed.

Limit-up/down sessions are not silently removed. Preserve limit prices and
record minute contact with either limit so a later representation can separate
mechanical price restriction from support defense. This audit makes no claim
about order queues, hidden liquidity, or participant intent.

## Frozen bounded audit

Two cohort identities are retained even if a security/date appears twice:

1. all 1,200 sessions in the accepted AUDIT-MKT-MIN-001 sample;
2. exactly five hash-selected supported cash/share action sessions per year for
   2018--2023, selected only from CY-006 after March 1 by
   `SHA256(MKT-SUPPORT-DATA-001|year|symbol|trade_date)`.

The action selection may not inspect minute completeness, support values, or
event behavior. The expected cohort count is 1,230. Every cohort row must have
valid 10/20/40 prior levels and an exact current minute coordinate.

Separately audit full daily 2018--2023 eligibility. After forty completed
exchange sessions, every date/view/denominator must retain at least ALL_A 1000,
SH_A 400, SZ_A 400, and CHINEXT_BOARD 200 eligible securities. No sample
replacement, imputation, relaxed population floor, or alternative source is
allowed.

## Claim boundary

Passing establishes only data and coordinate feasibility for a later objective
support representation map. It does not establish that a prior low is economic
support, that penetration is defended, that recovery reflects accumulation, or
that any state predicts return, habitat, timing, execution, or a strategy.
Future payoff, strategy outcomes, post-2023 data, and CY-011 are prohibited.
