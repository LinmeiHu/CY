# Champion confirmed-breakdown dynamic exit

Status: `COMPLETE_PHASE_B_STOP_NO_REPLAY`. Final classification: `BREAKDOWN_NOT_USEFUL_AS_EXIT`.

## Recovered support definition

The exact repository-authoritative event is a completed daily causal-coordinate close strictly below the minimum causal-coordinate low of the previous 20 completed hard-valid sessions. The support is known before the event day, updates daily, and the close-confirmed signal is recorded at 15:30. It does not use a minute low, an intraday crossing, a reclaim rule, or a penetration threshold. Because confirmation occurs only at the completed close, the earliest faithful fill is the next legal session open; an event-day intraday fill would be a different signal.

## Breakdown incidence

1,071 of 2,625 frozen champion positions had a first confirmed breakdown (40.80%); 582 securities, 230 cohorts, 6 years, and 102 industries were represented.
Actionable fill coverage was 95.24%; sellable inventory at confirmation was 96.64%. Full/partial/locked event groups were 831/2/34. Delayed/no-headroom/unexecuted lots were 25/51/0.
Holding-age counts were day_0 36, days_11_15 275, days_16_20 227, days_1_5 257, days_6_10 276.
There were 166 symbol-event groups with multiple active cohorts. Exit-before-entry ordering means older lots would be sold before any same-open frozen new cohort; the two partial confirmation states and 34 fully locked confirmation states are reported without illegal same-day sale assumptions.

## Post-breakdown path

| Period | N | h1 mean | h3 mean | h5 mean | Remaining mean | Remaining median | Matched remaining gap | MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full | 1,020 | 0.400% | 0.669% | 0.686% | 1.572% | 0.243% | -0.187% | -4.756% |
| early_2018_2021 | 615 | 0.437% | 0.584% | 0.530% | 1.562% | 0.370% | -0.611% | -4.968% |
| late_2022_2023 | 405 | 0.343% | 0.799% | 0.923% | 1.586% | 0.135% | 0.447% | -4.433% |
| loser_continuation | 1,017 | 0.399% | 0.673% | 0.698% | 1.572% | 0.250% | -0.200% | -4.749% |
| winner_giveback | 3 | 0.773% | -0.704% | -3.283% | 1.577% | -3.917% | 3.872% | -6.974% |

Matched-control coverage was 96.96%; the fraction recovering to a positive remaining payoff was 51.57%.

## Year-by-year original path

| Year | N | h1 | h3 | h5 | Remaining | Matched remaining gap |
|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 111 | 0.027% | -0.114% | -0.891% | 0.252% | 0.996% |
| 2019 | 164 | 0.072% | -0.062% | -0.015% | 0.572% | -0.496% |
| 2020 | 171 | 0.886% | 1.146% | 1.537% | 3.792% | -3.024% |
| 2021 | 169 | 0.608% | 1.100% | 0.973% | 1.129% | 0.585% |
| 2022 | 194 | 0.290% | 1.183% | 1.142% | 1.909% | 0.020% |
| 2023 | 211 | 0.391% | 0.445% | 0.722% | 1.289% | 0.841% |

## Executable replay

Not authorized. The original position path did not show adverse remaining economics, so the predeclared Phase-B gate stopped the experiment before any modified champion replay.

## Boundary

All evidence uses consumed 2018--2023 development history. Post-2023 outcomes and CY-011 were not read. No OOS, independent-validation, live, or production claim is made. No support variant, stop grid, re-entry rule, regime filter, or champion entry change was tested.
