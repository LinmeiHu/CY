# EXP-IBQ-002 structured evidence packet

## Question and mechanism

Does persistent demand/acceptance during the completed V1 entry-signal session
distinguish fixed MFE>=20% opportunities from the existing false-breakout class?

## Fixed measurement

The sole primary predictor is the equal-weight within-year rank composite of
signed one-minute path efficiency, time above full-session VWAP, and first-30-minute
peak retention. Daily OHLC/amount, V1 entry state, market/breadth, beta, liquidity,
and year are fixed controls. No component, threshold, horizon, or interaction is
selected from results.

## PIT and execution boundary

- Raw rows: 96159; exact 241-bar sessions: 399.
- The 09:30 auction bar is excluded from the primary continuous-session path and
  retained only in a frozen neighboring definition.
- Full-session features are available at 15:30 on the entry-signal date.
- Earliest potential action is T+1 open; same-session or already-completed open
  interpretation is forbidden.
- Full-depth order book, tick orders, queue, cancellations, and participant identity
  are unavailable and are not inferred.

## Results

- Decision: `REJECTED`.
- Verdict: `SIGNAL_DAY_PATH_ACCEPTANCE_FAILS_RAW_OR_DAILY_INCREMENTAL_GATES`.
- Gates: `{"controlled_daily_incrementality": false, "falsification": false, "outcome_neighbors": false, "raw": false, "temporal": false}`.
- Raw/controlled rho: `0.012339` / `-0.009117`.
- Raw/controlled LOYO: `6/8` / `2/8`.

## Interpretation boundary

Features are complete entry-signal-session observations available at 15:30 for T+1 or later. They cannot justify an earlier same-session action and do not identify the original lifecycle breakout timestamp.
