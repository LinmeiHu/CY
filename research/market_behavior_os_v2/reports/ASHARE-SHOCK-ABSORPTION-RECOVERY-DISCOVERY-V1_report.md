# A-share Shock Absorption / Recovery Discovery V1

## Executive conclusion

Final classification: `NULL`.

The frozen stronger-recovery Q5 is adverse to Q1 at every horizon and in every calendar year's h20 industry-relative comparison; it also has more severe losses and worse h20 MAE. This is neither absorption Alpha nor defensive information, and the sign is not inverted.

## Exact hypothesis and frozen event

A shock requires causal simple stock return <= -5% and stock-minus-PIT-industry leave-one-out return <= -3% on completed day s. The signal is not formed until exactly three further valid sessions complete. Recovery Fraction is [C(s+3)-C(s)]/[C(s-1)-C(s)]; Further Drawdown Ratio is max(0,C(s)-min(C(s+1:s+3)))/ShockLoss. All closes are accepted corporate-action coordinates. Earliest entry is the first later legal open.

## Event anatomy and actionability

There are 62,094 qualifying shocks before overlap suppression, 50,939 accepted non-overlapping shocks, and 50,201 ranked complete events across 1139 signal dates, 4,176 securities, and 118 industries.

Shock return median/p10/p90 is -6.780%/-10.000%/-5.281%. Recovery Fraction median/p10/p90 is -0.088/-1.135/1.189; Further Drawdown Ratio is 0.321/0.000/1.243.

Shock-event actionability is 99.89%: 50,030 immediate, 116 delayed, and 55 unusable.

## Raw Recovery Fraction results

| Horizon | Q1 net | Q2 net | Q3 net | Q4 net | Q5 net | Q5-Q1 net | Q5-Q1 industry-relative | Q5-Q1 median industry-relative | Q5-Q1 positive | Q5-Q1 severe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| h1 | -0.124% | -0.248% | -0.213% | -0.181% | -0.134% | -0.010% | -0.017% | -0.069% | -3.078% | +0.740% |
| h3 | +0.044% | +0.059% | -0.029% | +0.052% | -0.085% | -0.129% | -0.176% | -0.226% | -0.289% | +3.539% |
| h5 | -0.032% | +0.054% | +0.011% | +0.035% | -0.310% | -0.277% | -0.342% | -0.505% | -0.684% | +4.140% |
| h10 | -0.244% | +0.013% | -0.098% | -0.258% | -0.943% | -0.699% | -0.551% | -0.616% | -1.179% | +6.613% |
| h20 | -0.630% | -0.200% | -0.358% | -0.483% | -1.719% | -1.089% | -0.986% | -1.002% | -2.525% | +6.651% |

## Incrementality and chronology

| Diagnostic | h5 industry-relative Q5-Q1 | h20 industry-relative Q5-Q1 |
| --- | ---: | ---: |
| Shock recovery | -0.342% | -0.986% |
| Shock stabilization | -0.263% | -0.678% |
| Matched non-shock recovery | -0.049% | -0.578% |
| Early 2018-2021 | -0.429% | -0.768% |
| Late 2022-2023 | -0.204% | -1.344% |

## Year-by-year h20

| Year | Q5-Q1 net | Q5-Q1 industry-relative |
| --- | ---: | ---: |
| 2018 | -0.943% | -0.841% |
| 2019 | -1.366% | -1.155% |
| 2020 | +0.534% | -0.163% |
| 2021 | -0.750% | -1.047% |
| 2022 | -1.841% | -1.057% |
| 2023 | -2.575% | -1.839% |

## Shock severity and coarse controls

9 severity cells have at least 20 observations in both Q1 and Q5; 22.2% have positive h20 industry-relative ordering.

| Control | h20 tercile spreads |
| --- | --- |
| PRE_SHOCK_TREND | -0.973% / -1.035% / -1.106% |
| PRE_SHOCK_VOLATILITY | -0.563% / -0.880% / -1.630% |
| LIQUIDITY | -1.303% / -0.966% / -0.797% |
| LOW_MAX | -0.509% / -0.559% / -1.475% |

## Defensive versus Alpha and Strategy-A independence

At h20, Recovery Q5-Q1 net return is -1.089%, industry-relative spread is -0.986%, severe-loss change is +6.651%, and MAE change is -1.789%.

Low-MAX same-date rank correlation is 0.038; Champion Q5 overlap is 0.06%. No Strategy-A rule or result changed.

## Decision

`NULL`. Close this exact daily shock-absorption family and return to the previously resource-blocked frozen Cross-Sectional Dispersion science.

This is consumed 2018-2023 development evidence, not OOS confirmation. Post-2023 outcomes and CY-011 were not read.
