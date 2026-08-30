# Post-entry landmark emergence of the CHINEXT V1 right tail

EXP-PEL-001 asks when extreme winners first separate after entry. It is descriptive holding-path mechanism evidence, not an entry signal, exit rule, or causal prediction experiment.

## Landmark audit

- Frozen cycles: `399`; day-5/day-10/day-20 observable samples: `295` / `192` / `91`.
- Day-5 extreme winners/winner20: `15` / `39`.
- Causal-entry/post-exit/counterfactual/replay failures: `0` / `0` / `0` / `0`.
- Missing later landmarks are not imputed. Each horizon is conditioned on the trade remaining observable under the frozen strategy through that landmark.

## Primary day-5 test

| Raw rho | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Holding/exit rho | Ex-top-1% rho | Pass raw/control/neighbor/falsification |
|---:|---:|---:|---:|---:|---:|---:|---|
| 0.292 | 0.183 | 8/8 | 0.313 | 8/8 | 0.221 | 0.239 | Y/Y/Y/Y |

The controlled design uses only frozen pre-entry V1, market, breadth, beta, liquidity, and year state. Holding duration and exit reason are a separate post-outcome sensitivity because they are strategy-path mediators, not causal entry controls.

## Fixed later-landmark confirmation

| Landmark | N | Extreme-winner rho | Within-year rho | LOYO + |
|---|---:|---:|---:|---:|
| return_10d | 192 | 0.345 | 0.246 | 8/8 |
| return_20d | 91 | 0.504 | 0.381 | 8/8 |

## Outcome-class day-5 distribution

| Outcome class | N | Median day-5 return | Mean day-5 return |
|---|---:|---:|---:|
| extreme_winner | 15 | 0.261 | 0.396 |
| ordinary_loser | 128 | -0.015 | -0.011 |
| ordinary_winner | 94 | 0.033 | 0.050 |
| severe_loser | 34 | -0.068 | -0.063 |
| strong_winner | 24 | 0.149 | 0.196 |

## Scientific decision

`DEEPEN` / `RIGHT_TAIL_SEPARATES_BY_LANDMARK5_WITH_QUALIFICATION`.

Day-5 return is part of the future holding path and eventual trade return. Even a robust association would only locate when tail separation becomes visible; it cannot be called an entry edge, and this experiment does not test any sell/hold action.

## Strategy candidate

None. EXP-PEL-001 authorizes no entry, exit, ranking, sizing, or production change.
