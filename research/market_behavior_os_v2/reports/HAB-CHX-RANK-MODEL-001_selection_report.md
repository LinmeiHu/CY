# HAB-CHX-RANK-MODEL-001 — stock-selection comparison

All results below are Top-1 choices on complete multi-candidate dates. The learned models are fit only on prior calendar years.

| Ranker | Role | Mean dev | Severe dev | Mean 2022–23 | Severe 2022–23 |
|---|---|---:|---:|---:|---:|
| BASELINE_RS_SCORE | CURRENT_BASELINE | 3.125% | 16.7% | -3.172% | 25.6% |
| SINGLE_MINVOL_LOCATION | NO_ENGINE_REPLAY | 7.154% | 20.8% | -3.590% | 17.9% |
| EQ_COMPRESSION_DEFENSE | NO_ENGINE_REPLAY | 3.834% | 20.8% | -5.716% | 33.3% |
| EQ_PATIENT_SUPPLY | NO_ENGINE_REPLAY | 2.719% | 16.7% | -0.236% | 23.1% |
| EQ_BREAKOUT_ACCEPTANCE | NO_ENGINE_REPLAY | 7.919% | 20.8% | -3.152% | 28.2% |
| EQ_BALANCED_FIVE | NO_ENGINE_REPLAY | 2.796% | 20.8% | -2.092% | 23.1% |
| RIDGE_ALPHA_10 | NO_ENGINE_REPLAY | 7.338% | 20.8% | -2.244% | 12.8% |
| TREE_DEPTH_2 | NO_ENGINE_REPLAY | 3.511% | 16.7% | -4.157% | 15.4% |

Executable replay shortlist: none

This is consumed 2018–2023 research, not untouched validation. No post-2023 or CY-011 row was read, and realized outcome/path fields were not predictors.
