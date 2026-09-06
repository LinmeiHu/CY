# Phase 3 — Winner versus False Positive

OC-EXP-P3-001: **PASS** as an experiment; promotion remains subject to Phase 7 extreme/top-N sensitivity.

Tested `54` frozen causal-feature/outcome pairs. `0` pass the preregistered effect, yearly, LOYO, and BH gates before extreme sensitivity.

| Feature | Outcome | N | rho(year+breadth) | q(54) | Year + / - | LOYO + / - |
|---|---|---:|---:|---:|---:|---:|
| entry_rs_score | mfe | 387 | 0.137 | 0.261 | 7 / 1 | 8 / 0 |
| entry_box_width | severe_loss_classification | 387 | 0.119 | 0.261 | 6 / 1 | 8 / 0 |
| entry_mom60 | terminal_return | 387 | -0.119 | 0.261 | 4 / 4 | 0 / 8 |
| entry_rs_score | right_tail_classification | 387 | 0.116 | 0.261 | 6 / 1 | 8 / 0 |
| entry_rs_score | opportunity20 | 387 | 0.107 | 0.261 | 7 / 0 | 8 / 0 |
| entry_minimum_volume_ratio | mfe | 387 | -0.105 | 0.261 | 3 / 5 | 0 / 8 |
| entry_box_width | terminal_return | 387 | -0.104 | 0.261 | 0 / 8 | 0 / 8 |
| entry_breakout_volume_ratio | mfe | 387 | 0.104 | 0.261 | 5 / 3 | 8 / 0 |
| entry_rs_score | false_breakout | 387 | -0.102 | 0.261 | 1 / 7 | 0 / 8 |
| entry_mom60 | severe_loss_classification | 387 | 0.102 | 0.261 | 6 / 1 | 8 / 0 |
| entry_breakout_volume_ratio | opportunity20 | 387 | 0.092 | 0.342 | 5 / 2 | 8 / 0 |
| entry_mom120 | terminal_return | 387 | -0.088 | 0.342 | 5 / 3 | 0 / 8 |
| entry_box_width | opportunity20 | 387 | -0.086 | 0.342 | 3 / 4 | 0 / 8 |
| entry_vol_ratio | false_breakout | 387 | -0.084 | 0.342 | 2 / 6 | 0 / 8 |
| entry_mom20 | severe_loss_classification | 387 | 0.083 | 0.342 | 6 / 1 | 8 / 0 |
| entry_vol_ratio | mfe | 387 | 0.083 | 0.342 | 6 / 2 | 8 / 0 |
| entry_breakout_volume_ratio | severe_loss_classification | 387 | 0.081 | 0.342 | 6 / 1 | 8 / 0 |
| entry_rs_score | terminal_return | 387 | 0.081 | 0.342 | 6 / 2 | 8 / 0 |

Same-year nearest-breadth comparison formed `37` right-tail/false-breakout pairs using `25` distinct false breakouts. Matching uses outcomes only for diagnosis and is not a classifier.

P-values use an asymptotic Fisher-z approximation on partial rank residuals. Effect magnitude and temporal stability, not nominal significance alone, govern promotion.
