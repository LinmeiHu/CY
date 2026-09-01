# Champion strategy anatomy — Industry Diffusion + Weekly Low-MAX

## Executive conclusion

Lifecycle classification: `FULL_HORIZON_PERSISTENT`. Rank classification: `BREADTH_ECONOMICALLY_SUPPORTED`. Final anatomy: `CONCENTRATED_BUT_ECONOMICALLY_MEANINGFUL`.

Structural decision: `NO_CHAMPION_MODIFICATION_RETURN_TO_INDEPENDENT_ALPHA`. The frozen strategy was not changed.

Alpha is not front-loaded: the mean trade is still negative after d1, reaches only 0.23% by d5, and earns 0.81% after d10. Ranks 6--10 remain positive in both broad blocks and contribute 43.24% of net trade PnL, so the frozen Top 10 has economic breadth rather than an obviously dilutive tail.

Opportunity richness does not order outcomes monotonically: normal cohorts are strongest overall, while the rich-minus-sparse relation reverses between the two broad blocks. Industry-state persistence is associated with stronger subsequent payoff, but faded cohorts remain profitable and the d10 gap misses the frozen exit gate. Neither adaptive breadth nor a state-linked exit earned a construction experiment.

## Alpha lifecycle

| Checkpoint | Mean cumulative | Early mean | Late mean | Median | Winner | Severe | Mean incremental |
|---:|---:|---:|---:|---:|---:|---:|---:|
| d1 | -0.18% | -0.23% | -0.13% | -0.40% | 41.33% | 0.53% | -0.18% |
| d3 | 0.07% | 0.06% | 0.08% | -0.40% | 45.41% | 2.13% | 0.25% |
| d5 | 0.23% | 0.42% | 0.06% | -0.40% | 46.32% | 3.89% | 0.16% |
| d10 | 0.67% | 0.82% | 0.54% | -0.13% | 49.30% | 7.54% | 0.44% |
| d15 | 1.08% | 1.29% | 0.89% | -0.29% | 48.42% | 10.63% | 0.41% |
| d20 | 1.48% | 2.11% | 0.92% | -0.30% | 48.99% | 14.13% | 0.40% |

The already-authoritative candidate/control h20 excess is 0.40% full, 0.59% early, and 0.23% late; it is reported for context and was not reconstructed into intermediate checkpoint controls.

## Rank anatomy

| Frozen rank bucket | Trades | Mean | Early | Late | Median | Winner | Severe | Net-PnL share | Industry HHI | P10 capacity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ranks_1_2 | 525 | 0.95% | 1.91% | 0.13% | -0.40% | 48.38% | 12.95% | 9.38% | 0.027 | CNY 102,606,268 |
| ranks_3_5 | 788 | 2.21% | 3.31% | 1.26% | 0.24% | 50.63% | 13.96% | 47.37% | 0.023 | CNY 110,772,188 |
| ranks_6_10 | 1312 | 1.24% | 1.48% | 1.04% | -0.40% | 48.25% | 14.71% | 43.24% | 0.023 | CNY 116,039,741 |

## Opportunity richness

| Regime | Dates | Trades | Mean cohort | Early | Late | Winner | Severe | Net-PnL share | P10 capacity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sparse | 88 | 879 | 1.47% | 2.69% | -0.06% | 50.40% | 16.27% | 23.00% | CNY 115,945,643 |
| normal | 88 | 878 | 2.14% | 2.76% | 1.56% | 50.91% | 12.87% | 54.40% | CNY 110,438,079 |
| rich | 87 | 868 | 0.83% | 0.41% | 1.06% | 45.62% | 13.25% | 22.60% | CNY 109,119,941 |

## Contribution concentration

Top-five industries contribute 58.84% of net PnL; top-ten decision dates 69.14%; top-twenty securities 66.18%.

Positive/negative years: 4/2. Leave-largest-industry/year/date returns are 102.41%/67.21%/106.23%.

Year contributions to initial capital are 2018 -19.00%, 2019 36.41%, 2020 55.22%, 2021 31.67%, 2022 -9.40%, 2023 27.54%.

## Industry-thesis persistence

| Checkpoint | Persistence | Persistent subsequent | Faded subsequent | Gap |
|---:|---:|---:|---:|---:|
| d5 | 30.03% | 2.02% | 1.01% | 1.01% |
| d10 | 19.16% | 1.06% | 0.79% | 0.27% |
| d15 | 10.35% | 0.76% | 0.24% | 0.52% |
| d20 | 5.73% | 0.00% | 0.00% | 0.00% |

## Structural decision

`NO_CHAMPION_MODIFICATION_RETURN_TO_INDEPENDENT_ALPHA`. Exactly zero strategy changes or new Alpha tests were run.

All evidence is consumed 2018--2023 development history. Post-2023 outcomes and CY-011 remained unread. No independent-validation, OOS, live, or production claim is made.
