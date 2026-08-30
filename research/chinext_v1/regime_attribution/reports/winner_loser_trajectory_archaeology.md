# Winner/loser pre-entry trajectory archaeology

EXP-WLA-001 is exploratory mechanism evidence over already-consumed 2018-2025 outcomes. It uses no strategy replay, post-entry price, threshold search, interaction search, or strategy modification.

## Integrity and PIT audit

- Frozen completed cycles: `399`; complete trade/anchor panels: `399`.
- Trajectory rows: `2793` at fixed anchors T-60/T-40/T-20/T-10/T-5/T-3/T-1.
- T-1 is the completed entry-signal close; it is applicable only to the later first-valid entry execution.
- Hard-valid/coordinate/causal failures: `0` / `0` / `0`.
- Strategy replays: `0`; post-entry price rows read: `0`.
- Stock returns use the existing visible-action causal coordinate. Downside traded-amount share is a proxy based on negative-return sessions, not order-flow classification.

## Fixed outcome groups

| Group | N |
|---|---:|
| extreme_winner | 15 |
| ordinary_loser | 194 |
| ordinary_winner | 122 |
| severe_loser | 44 |
| strong_winner | 24 |

## Preregistered primary transition tests

All four transitions are oriented so a positive association supports the proposed extreme-winner mechanism.

| Transition | Raw rho | BH q | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Neighbor rho | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| rs_improvement | 0.022 | 0.987 | -0.001 | 7/8 | 0.018 | 6/8 | 0.020 | NO |
| volatility_compression | 0.001 | 0.987 | 0.018 | 6/8 | 0.006 | 6/8 | -0.033 | NO |
| range_compression | -0.074 | 0.565 | -0.036 | 0/8 | -0.090 | 0/8 | -0.027 | NO |
| downside_amount_contraction | 0.014 | 0.987 | 0.020 | 7/8 | 0.003 | 6/8 | 0.010 | NO |

The fixed controlled design includes V1 entry RS/momentum/box/minimum-volume/breakout-volume state, entry-year effects, market return/volatility, frozen breadth, trailing stock beta, and traded-amount liquidity. The neighbor uses T-3 in place of T-1 or T-5; it cannot replace the primary definition.

## Group trajectories at the key anchors

| Group | Anchor | Relative strength20 median | Vol20 median | Range20 median | Downside-amount share median |
|---|---:|---:|---:|---:|---:|
| extreme_winner | T-20 | 0.030 | 0.390 | 0.154 | 0.446 |
| extreme_winner | T-5 | 0.041 | 0.353 | 0.166 | 0.420 |
| extreme_winner | T-1 | 0.096 | 0.487 | 0.184 | 0.350 |
| ordinary_loser | T-20 | -0.005 | 0.411 | 0.158 | 0.435 |
| ordinary_loser | T-5 | 0.028 | 0.371 | 0.150 | 0.414 |
| ordinary_loser | T-1 | 0.084 | 0.402 | 0.171 | 0.339 |
| ordinary_winner | T-20 | 0.010 | 0.398 | 0.152 | 0.452 |
| ordinary_winner | T-5 | 0.020 | 0.371 | 0.146 | 0.411 |
| ordinary_winner | T-1 | 0.080 | 0.395 | 0.175 | 0.356 |
| severe_loser | T-20 | -0.025 | 0.441 | 0.175 | 0.438 |
| severe_loser | T-5 | -0.005 | 0.421 | 0.161 | 0.409 |
| severe_loser | T-1 | 0.082 | 0.476 | 0.189 | 0.321 |
| strong_winner | T-20 | 0.027 | 0.366 | 0.153 | 0.430 |
| strong_winner | T-5 | 0.002 | 0.385 | 0.145 | 0.470 |
| strong_winner | T-1 | 0.058 | 0.414 | 0.176 | 0.360 |

## Active falsification

| Transition | Ex-top-1% rho | Holding/exit controlled rho | Industry-FE rho | Security omission + | Industry omission + | Falsification pass |
|---|---:|---:|---:|---:|---:|---|
| rs_improvement | 0.003 | -0.002 | 0.029 | 1.000 | 0.985 | NO |
| volatility_compression | -0.011 | 0.034 | 0.036 | 0.500 | 0.794 | NO |
| range_compression | -0.095 | -0.076 | -0.104 | 0.000 | 0.000 | NO |
| downside_amount_contraction | 0.055 | -0.002 | -0.000 | 0.857 | 0.971 | NO |

## Scientific decision

`REJECT`. Passing components: `none`. A coherent demand-plus-compression mechanism requires RS improvement and at least one independently passing compression/supply transition.

A positive historical difference is not a filter, threshold, or candidate. All existing outcomes are consumed and the underlying security/universe data are bounded PIT-B, not untouched PIT-A.

## Strategy candidate

None. EXP-WLA-001 authorizes no entry, sizing, ranking, exit, or production change.
