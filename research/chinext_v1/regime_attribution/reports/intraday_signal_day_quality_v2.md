# Intraday entry-signal-session path quality

EXP-IBQ-002 tests one preregistered path-acceptance composite on the completed
entry-signal session. It does not identify the earlier lifecycle breakout date,
does not test a rule, and cannot be used before its 15:30 availability timestamp.

## Integrity and PIT

- Completed cycles / raw bars: `399` / `96159`.
- Hard-valid CY-008 daily rows / opening windows: `399` / `2394`.
- Maximum raw-versus-CY-008 opening-window relative difference: `0`.
- Available at: `entry signal session 15:30 Asia/Shanghai`.
- Potential action: `T+1 open or later; never same-session`.

## Primary evidence

| Metric | Estimate |
|---|---:|
| Raw success-vs-false rho | 0.012 |
| Within-year rho | 0.015 |
| Raw LOYO positive | 6/8 |
| Daily/incrementality-controlled rho | -0.009 |
| Controlled LOYO positive | 2/8 |

## Decision

`REJECTED` — `SIGNAL_DAY_PATH_ACCEPTANCE_FAILS_RAW_OR_DAILY_INCREMENTAL_GATES`.

Features are complete entry-signal-session observations available at 15:30 for T+1 or later. They cannot justify an earlier same-session action and do not identify the original lifecycle breakout timestamp.
