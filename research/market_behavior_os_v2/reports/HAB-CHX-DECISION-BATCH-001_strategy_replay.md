# HAB-CHX-DECISION-BATCH-001 — fixed selection and risk-budget replays

Two predeclared decision translations were replayed through the unchanged CHINEXT V1 execution engine. Both blocks are consumed exploration.

| Arm | Block | Baseline return | Candidate return | Delta | Baseline DD | Candidate DD | Sharpe delta | Cycles |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| RS_ACCEL_OVEREXTENSION_VETO | development_2018_2021 | 64.822% | 66.777% | 1.955% | -20.763% | -18.717% | 0.127 | 139 / 194 |
| RS_ACCEL_OVEREXTENSION_VETO | consumed_2022_2023 | -15.522% | -8.734% | 6.788% | -19.341% | -13.191% | 0.337 | 74 / 94 |
| MINVOL_HIGH_HALF_GROSS | development_2018_2021 | 64.822% | 66.582% | 1.760% | -20.763% | -15.462% | 0.132 | 194 / 194 |
| MINVOL_HIGH_HALF_GROSS | consumed_2022_2023 | -15.522% | -9.329% | 6.193% | -19.341% | -13.601% | 0.211 | 94 / 94 |

## Decisions

- `RS_ACCEL_OVEREXTENSION_VETO`: `STRATEGY_CANDIDATE_RS_ACCEL_OVEREXTENSION_VETO`. Failed gates: none.
- `MINVOL_HIGH_HALF_GROSS`: `STRATEGY_CANDIDATE_MINVOL_HIGH_HALF_GROSS`. Failed gates: none.

The selection arm changes only which new candidates are admitted. The exposure arm changes only selected-position target weights on broad state transitions; it keeps the holding set, ranking, exits, T+1, limits, costs, and corporate-action handling intact.

No post-2023 row or CY-011 input was read by this experiment. Because unrelated post-2023 summary metadata was accidentally exposed during repository inventory, future confirmation must use a separately quarantined block.
