# Phase 9 — active failure and falsification test

EXP-P8P9-001 candidate verdict: `REJECT_V1R_KEEP_FROZEN_V1`.

| # | Challenge | Verdict |
|---:|---|---|
| 1 | Is apparent value only market-beta timing? | `NON_BETA_VALUE_NOT_ESTABLISHED` |
| 2 | Is lower drawdown merely lower exposure? | `EXPOSURE_REDUCTION_CONFOUND_PRESENT` |
| 3 | Does it sacrifice future true winners? | `LIMITED_BUT_NONZERO_RIGHT_TAIL_SACRIFICE` |
| 4 | Do only one or two years support it? | `TEMPORAL_STABILITY_REJECTED` |
| 5 | Is it threshold mining? | `PRIMARY_WAS_PREREGISTERED_BUT_RELATION_IS_THRESHOLD_SENSITIVE` |
| 6 | Does it depend on a few extreme trades? | `V1_REMAINS_EXTREME_TRADE_DEPENDENT_AND_OVERLAY_DOES_NOT_RESOLVE_IT` |
| 7 | Is the regime stably identifiable? | `STATE_IDENTIFICATION_LIMITED` |
| 8 | Is there a realistic PIT implementation problem? | `NO_LEDGER_LEVEL_PIT_OR_EXECUTION_DEFECT_FOUND` |
| 9 | Does a neighboring definition erase the relation? | `YES_NEIGHBORING_ROBUSTNESS_FAILS` |
| 10 | Does complexity exceed practical benefit? | `RULE_IS_SIMPLE_BUT_BENEFIT_IS_INSUFFICIENT` |

## Interpretation

The strongest pro-candidate evidence is implementation cleanliness, stable observability of the raw breadth state, lower turnover, and limited rather than catastrophic right-tail sacrifice. None rescues portfolio usefulness: bad-year and neighbor gates fail, yearly/rolling/LOYO evidence is not broad, and exposure-normalized performance is materially worse in 2018-2021.

The primary threshold was preregistered and was not mined. The failure is instead economic sensitivity: moving to the frozen neighboring definitions changes which years improve, and the apparently favorable 0.50 holdout arm cannot be selected after results. The rule is simple, but complexity-adjusted benefit is still insufficient.

H-010 is supported: breadth remains explanatory for favorable-path opportunity, but no tested V1-R overlay is justified. Frozen V1 remains the strategy baseline.
