# ASHARE-MARKET-PANIC-REPAIR-TRANSITION-V1

Verdict: `NO_PANIC_REPAIR_TRANSITION_EDGE`

This Development-only market-state experiment used 2014–2021 data. Validation (2022–2023) and Final OOS (2024+) remained sealed.

## Contract and population

Opening panic is the equal-weight TRAIN empirical-CDF score of 5% down-gap breadth, inverted median open return, and registered lower-limit stress breadth. Repair is observed only at 09:45, 10:00, or 10:30; entry is the first minute strictly afterward. Main Board and ChiNext were calibrated and selected independently.

- MAIN: 1950 dates; full-development Q75/Q90 panic counts 488/196; panic-score q10/median/q90 0.312/0.515/0.817.
  Repair-score q10/median/q90: 09:45 0.256/0.530/0.807; 10:00 0.242/0.528/0.808; 10:30 0.240/0.528/0.816.
- CHINEXT: 1950 dates; full-development Q75/Q90 panic counts 489/195; panic-score q10/median/q90 0.398/0.588/0.824.
  Repair-score q10/median/q90: 09:45 0.230/0.527/0.845; 10:00 0.219/0.530/0.843; 10:30 0.211/0.527/0.857.

## Walk-forward evidence

### MAIN

| Test | Frozen champion | Full return | MaxDD | Sharpe | Trades | Panic-only | Increment | Ordinary repair | Top-5 OOS median |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `pQ75|t1000|rQ67|xT1_CLOSE` | -1.33% | -6.31% | -0.319 | 12 | -21.55% | 20.21% | -6.41% | -1.33% |
| 2018 | `pQ75|t1000|rQ67|xT1_CLOSE` | -11.19% | -24.81% | -0.707 | 35 | -48.12% | 36.92% | -9.09% | -4.01% |
| 2019 | `pQ75|t1000|rQ67|xT1_CLOSE` | -8.32% | -15.73% | -0.766 | 18 | -12.59% | 4.27% | -8.07% | -8.32% |
| 2020 | `pQ75|t1000|rQ67|xT1_CLOSE` | -3.35% | -12.89% | -0.182 | 14 | -9.78% | 6.43% | 11.71% | 4.72% |
| 2021 | `pQ75|t1030|rQ67|xT1_CLOSE` | -0.71% | -3.55% | -0.138 | 12 | -16.76% | 16.05% | 1.06% | -0.88% |

Stitched: return -22.91%, CAGR -5.04%, MaxDD -28.92%, Sharpe -0.437, Calmar -0.174, trades 91.
Calendar-year returns: 2017 -1.33%, 2018 -11.19%, 2019 -8.32%, 2020 -3.35%, 2021 -0.71%; positive/negative/flat years 0/5/0; positive months 20.
Return excluding 2020: -20.24%; excluding best day: -26.49%; excluding best five days: -34.86%.
Positive-PnL concentration (top 1 day / top 5 days / top 1% days): 5.16% / 17.24% / 37.37%.
Board classification: `NO_PANIC_REPAIR_TRANSITION_EDGE`.

Profitable-versus-losing selected-session trajectories are preserved per fold in the result JSON. They do not show a clean, board-stable monotone repair path; in particular, high repair scores coexist with losing ChiNext 2018 sessions.

### CHINEXT

| Test | Frozen champion | Full return | MaxDD | Sharpe | Trades | Panic-only | Increment | Ordinary repair | Top-5 OOS median |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `pQ90|t0945|rQ80|xT1_CLOSE` | 0.00% | 0.00% | 0.000 | 0 | -0.34% | 0.34% | -2.36% | 1.68% |
| 2018 | `pQ75|t0945|rQ67|xT1_LEGAL_OPEN` | -4.37% | -6.11% | -0.907 | 8 | -9.69% | 5.32% | 1.75% | -7.53% |
| 2019 | `pQ75|t1000|rQ67|xT1_CLOSE` | -8.89% | -20.02% | -0.633 | 15 | -6.37% | -2.52% | 11.68% | 0.87% |
| 2020 | `pQ90|t0945|rQ67|xT1_LEGAL_OPEN` | 13.18% | -1.74% | 2.232 | 7 | -6.41% | 19.60% | 16.88% | 3.28% |
| 2021 | `pQ90|t0945|rQ67|xT1_LEGAL_OPEN` | 1.05% | 0.00% | 1.697 | 2 | 1.05% | 0.00% | -14.13% | 1.05% |

Stitched: return -0.36%, CAGR -0.07%, MaxDD -20.28%, Sharpe 0.024, Calmar -0.004, trades 32.
Calendar-year returns: 2017 0.00%, 2018 -4.37%, 2019 -8.89%, 2020 13.18%, 2021 1.05%; positive/negative/flat years 2/2/1; positive months 13.
Return excluding 2020: -11.96%; excluding best day: -5.01%; excluding best five days: -15.05%.
Positive-PnL concentration (top 1 day / top 5 days / top 1% days): 12.09% / 38.83% / 76.46%.
Board classification: `NO_PANIC_REPAIR_TRANSITION_EDGE`.

Profitable-versus-losing selected-session trajectories are preserved per fold in the result JSON. They do not show a clean, board-stable monotone repair path; in particular, high repair scores coexist with losing ChiNext 2018 sessions.

## Combined and mechanism

The fixed 50/50 portfolio returned -11.64%, with CAGR -2.43%, MaxDD -21.38%, Sharpe -0.319, and Calmar -0.114. Return excluding 2020 was -16.04%.

Repair confirmation improved the corresponding panic-only replay in 8 of 10 board-years. Checkpoint-stable evidence: True. Episode-concentrated evidence: True.

Selected-checkpoint repair increments: 0945: 3/4 positive, mean 6.31%, 1000: 4/5 positive, mean 13.06%, 1030: 1/1 positive, mean 16.05%.

The ordinary-day repair and transparent repair-bin results are diagnostic only and are preserved in the machine-readable result. No index proxy was reported because no already-certified board index instrument was available under this experiment's frozen inputs.

## Correctness audit

- `OPEN_PANIC_USES_POST_OPEN_DATA_COUNT`: `0`
- `REPAIR_SCORE_USES_POST_CHECKPOINT_DATA_COUNT`: `0`
- `TEST_YEAR_USED_IN_OWN_PARAMETER_SELECTION_COUNT`: `0`
- `TEST_YEAR_USED_TO_CALIBRATE_OWN_PANIC_COUNT`: `0`
- `TEST_YEAR_USED_TO_CALIBRATE_OWN_REPAIR_THRESHOLD_COUNT`: `0`
- `CROSS_BOARD_STATE_CONTAMINATION_COUNT`: `0`
- `PIT_INDUSTRY_IDENTITY_FAILURE_COUNT`: `0`
- `POST_2021_OUTCOME_READ_COUNT`: `0`
- `DUPLICATE_BOARD_POSITION_COUNT`: `0`
- `NEGATIVE_CASH_OR_LEVERAGE_COUNT`: `0`
- `VALIDATION_OPENED`: `False`
- `FINAL_OOS_OPENED`: `False`

## Interpretation

The frozen early market internals do not identify a sufficiently stable executable Panic-to-Repair transition. Close this exact transition representation rather than adding rescue indicators.

Validation readiness: `NO`. The exact representation is closed; 2022–2023 was not opened.
