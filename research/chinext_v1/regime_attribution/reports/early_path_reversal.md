# Early held-path reversal and post-day-5 failure

EXP-EPR-001 tests one continuous close-peak-to-day-5 giveback feature. It is holding-path mechanism evidence, not an entry or exit rule.

## Integrity and sample

- Day-5 survivors / path rows: `295` / `1475`.
- Early corporate-action cycles: `5`; hard-invalid/action-invalid rows: `0` / `0`.
- Accepted day-5 returns reconstruct to <=1e-12 under exact share/cash action accounting.
- No post-exit row, counterfactual exit, replay, threshold, or strategy rule was used.

## Frozen tests

| Test | Estimate | LOYO + |
|---|---:|---:|
| Giveback vs future failure | 0.032 | 7/8 |
| Controlled beyond day-5 state | 0.061 | 8/8 |
| Giveback vs false breakout | 0.306 | 8/8 |
| Giveback vs H-016 topology | 0.418 | 8/8 |
| High-based neighbor vs future failure | 0.064 | 7/8 |

## Decision

`REJECT` / `NO_STABLE_EARLY_REVERSAL_TO_FUTURE_FAILURE_MECHANISM`.

Frozen gates raw/control/false-breakout/neighbor/falsification: `False` / `False` / `True` / `True` / `False`.

No entry, ranking, sizing, holding, exit, or production modification was tested or authorized.
