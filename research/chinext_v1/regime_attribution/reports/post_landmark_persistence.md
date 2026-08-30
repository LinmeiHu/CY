# Post-landmark persistence falsification

EXP-PLP-001 removes day-5 return from terminal return multiplicatively, then asks whether early strength is associated with the return earned afterward. It is holding-path attribution, not a sell/hold experiment.

## Integrity and arithmetic

- Primary/later survivor samples: `295` / `192` / `91`.
- Maximum day-5 reconstruction error: `2.776e-16`.
- Post-exit price rows/replays/counterfactual paths/rules tested: `0` / `0` / `0` / `0`.

## Primary day-5 residual-return test

| Raw rho | Within-year rho | LOYO + | Pre-entry controlled rho | LOYO + | Duration/exit rho | LOYO + | Ex-top-1% | Ex-severe-loss |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.045 | -0.026 | 1/8 | -0.073 | 0/8 | -0.288 | 0/8 | -0.080 | -0.120 |

## Fixed later-landmark confirmation

| Landmark | N | Raw rho | Within-year rho | LOYO + |
|---|---:|---:|---:|---:|
| day 10 | 192 | 0.019 | 0.027 | 6/8 |
| day 20 | 91 | -0.258 | -0.070 | 0/8 |

## Preregistered gates

- Raw / pre-entry controlled / mechanical / neighbor: `FAIL` / `FAIL` / `FAIL` / `FAIL`.

## Scientific decision

`REJECT` / `DAY5_SEPARATION_DOES_NOT_IMPLY_INCREMENTAL_POST_DAY5_PERSISTENCE`.

Residualization removes the direct fact that day-5 return is contained in terminal return. It does not remove survivor conditioning or the strategy's frozen exit mechanics, so even a surviving association is descriptive and cannot authorize a hold rule.

## Strategy candidate

None. No entry, hold, exit, ranking, sizing, or production modification was tested or authorized.
