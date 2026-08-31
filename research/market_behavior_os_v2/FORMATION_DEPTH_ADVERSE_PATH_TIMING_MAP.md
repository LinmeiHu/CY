# Formation-depth adverse-path timing map

Frozen after MKT-FORMDEPTH-CLOSE-001 and before constructing any open/low/close
response component. The question is where the accepted crossing-security adverse
path is delivered: before the trough session opens, during that session after the
open, or as a temporary low that subsequently recovers by the fixed horizon.

## Scientific boundary

The predictor remains the exact completed-session market formation-depth level at
the 15:30 Asia/Shanghai information clock. Exact `cross20` membership is fixed at
t. No future open, low, close, trough day, closing arm, survival status, or path
component may become an entry predictor or redefine membership. Response begins
at the next exchange session and is post-decision attribution only.

Use the accepted CY-006 supported-action coordinate. For each security and h in
exactly {1,3,5}, find the earliest session j in 1..h with the minimum mapped low.
Ties go to the earliest offset. Define:

- `PREOPEN_PATH_TO_TROUGH_h = log(mapped_open_j / coordinate_close_t)`;
- `ADVERSE_h = log(mapped_low_j / coordinate_close_t)`;
- `TROUGH_SESSION_INTRADAY_h = ADVERSE_h - PREOPEN_PATH_TO_TROUGH_h`;
- `TERMINAL_h = log(coordinate_close_th / coordinate_close_t)`;
- `POST_TROUGH_RECOVERY_h = TERMINAL_h - ADVERSE_h`.

The residual definitions are canonical. They avoid inventing a floating tolerance
for log-addition identities. Economically they are the trough-session open-to-low
move and trough-low-to-horizon-close recovery. At h=1, the pre-open component is
the literal next-session close-to-open gap. At h=3/5 it is a cumulative pre-open
path to the trough session, not a pure overnight-gap measure.

## Primary population and controls

Primary estimates use all exact crossing securities. Closing-accepted and
closing-rejected arms are mandatory robustness views; exact equality remains
count-only. The response panel must retain the same fixed complete-five-session
cohort and the same 6,627-row five-control domain established by CLOSE-001.

Use the unchanged controls: causal discovery breadth, causal realized volatility,
central signed limit utilization, market median open-close return, and median
intraday range. This is not a within-security causal regression; it is a market-
date association decomposition.

## Fixed channels and gates

Classifying downside channels are:

1. `PREOPEN_PATH_DOWNSIDE`;
2. `TROUGH_SESSION_INTRADAY_DOWNSIDE`.

For each channel, h=3 is primary and h=1/h=5 are mandatory neighbors. A channel
passes only if the combined crossing mean satisfies the existing arm gate:
median h=3 PIT partial rho <=-0.10, at least six negative cells, both block
medians <=-0.05, every 2020--2023 year and leave-one-year-out negative, h=1/h=5
negative, at least two of three h=3 and four of five h=5 phases negative, and
controlled PIT-tail residual gap <=-0.0025. In addition, accepted and rejected
h=3 median PIT partial rhos must each be negative. Arm robustness does not create
a second favorable-arm classification.

`POST_TROUGH_RECOVERY` and terminal return are diagnostic-only because recovery
is mechanically linked to the already-selected adverse low and cannot promote or
rescue a timing classification.

Classifications are exhaustive and ordered:

- both downside channels pass: `MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH`;
- pre-open only: `PREOPEN_PATH_LOCALIZED_DOWNSIDE`;
- intraday only: `TROUGH_SESSION_INTRADAY_LOCALIZED_DOWNSIDE`;
- neither: `ADVERSE_PATH_TIMING_NOT_RESOLVED`.

Passing localizes association timing under this daily-bar decomposition. It does
not establish causality, a tradable overnight gap, minute-level execution,
temporary-loss tolerance, recovery capture, a habitat, or a strategy rule.
Closing-state and terminal failures remain binding. V1, post-2023 data, strategy
outcomes, and CY-011 remain closed.
