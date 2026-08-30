# EXP-EPR-001 evidence packet — early held-path reversal

## Decision

`REJECT` H-019's forward persistence mechanism. Close-peak giveback by day 5
describes which trades are already false breakouts and aligns with completed H-016
path order, but it does not explain additional return failure after day 5.

## Integrity

- Frozen sample: 295 day-5 survivors and 1,475 exact held-path rows.
- All rows are hard-valid; all action-coordinate steps pass.
- Five paths contain early corporate actions handled by exact share/cash accounting.
- Accepted day-5 return reconstruction error: `3.54e-16` maximum.
- No post-exit price, counterfactual exit, replay, threshold, or strategy rule.
- Eight-input-plus-spec aggregate: `fe431fab...`.
- Preexisting 236-file aggregate before/after both executions: `e5afd9e2...`.
- Two complete executions are byte-identical.

## Evidence

| Frozen test | Estimate | LOYO direction | Gate |
|---|---:|---:|---:|
| Giveback vs future failure | rho 0.032 | 7/8 positive | fail magnitude |
| Controlled beyond day-5 return/state | partial rho 0.061 | 8/8 positive | fail magnitude |
| Duration/exit controlled | partial rho 0.040 | — | fail |
| High-based giveback neighbor | rho 0.064 | 7/8 positive | neighbor component pass |
| Giveback vs false breakout | rho 0.306 | 8/8 positive | pass |
| Giveback vs H-016 topology | rho 0.418 | 8/8 positive | pass |

The future-failure block rhos are 0.052, 0.005, and -0.026. Removing the Top-4
P&L cycles, severe losses, or extreme winners leaves rhos 0.008, -0.008, and
0.006. The primary persistence result is therefore not merely just below a gate;
it collapses under the fixed tail and block attacks.

## Falsification interpretation

The strong false-breakout/topology associations locate an early completed-path
signature, but the primary temporal test prevents interpreting it as a persistent
failure process. At the same accepted day-5 state and fixed pre-entry controls,
interim peak giveback adds only partial rho 0.061 for later return.

This result does not support a day-5 sell rule. Testing such a rule would require
a counterfactual strategy modification on fully consumed data and is forbidden by
the experiment contract.

## Output identities

- table: `22990a28dd14f288d9b0af679c8c7532d8852b427b1546aa7374a4f8de997472`;
- JSON: `e1d646e5a2d7fd066a8f48b65506648353a0023001fdcf5eb0632275ae037a63`;
- generated report: `4c5367aa40a353dfb2eaa33fbfb46637c1968e6baff996798bfb9bf91a1103b3`.
