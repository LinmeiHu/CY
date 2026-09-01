# A-share downside resilience discovery V1

## Executive conclusion

Final classification: `NULL`.

The frozen orientation is adverse: stronger measured resilience under industry pressure trails at every tested horizon and in every calendar year, and the negative ordering remains inside the coarse generic-RS, volatility, liquidity, and Low-MAX controls. It is classified NULL as a long-only Alpha family and is not sign-inverted.

## Scientific question and frozen representation

The test asks whether stock-minus-PIT-industry residuals specifically on industry-down sessions contain future information beyond ordinary relative strength and low volatility. `IND_DOWN_RESILIENCE_20` is the mean daily residual on at least five industry-down observations in the 20 completed sessions ending at the weekly close. Industry pressure is the fixed prior-five-session PIT-industry return below zero. The signal is known at 15:30 and can enter only at a later legal open.

## Coverage and actionability

The panel contains 492,332 stock-date signals on 264 weekly dates, 4,649 securities, and 119 PIT industries from 2018-07-30 through 2023-12-27. Complete h20 outcomes end no later than 2023-12-28.

Actionability is 99.99%: 491,352 immediate, 945 delayed, and 35 unusable observations. Immediate-open blocks are 717 price-limit, 97 suspension/nontrading, and 166 invalid/unavailable-open observations.

## Raw cross-sectional result — industry pressure

| Horizon | Q1 net | Q2 net | Q3 net | Q4 net | Q5 net | Q5-Q1 net | Q5-Q1 industry-relative | Q5-Q1 median industry-relative | Q5-Q1 positive | Q5-Q1 severe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| h1 | -0.444% | -0.440% | -0.454% | -0.493% | -0.481% | -0.037% | -0.039% | -0.019% | -2.700% | +0.394% |
| h3 | -0.005% | -0.040% | -0.096% | -0.170% | -0.243% | -0.238% | -0.246% | -0.101% | -2.123% | +0.755% |
| h5 | +0.020% | -0.000% | -0.094% | -0.206% | -0.369% | -0.389% | -0.406% | -0.179% | -1.624% | +0.640% |
| h10 | -0.063% | -0.128% | -0.182% | -0.362% | -0.672% | -0.609% | -0.628% | -0.243% | -1.561% | +0.820% |
| h20 | +0.052% | -0.079% | -0.071% | -0.353% | -0.967% | -1.019% | -1.027% | -0.455% | -2.542% | -0.082% |

## Pressure specificity and chronology

| Slice | h5 industry-relative Q5-Q1 | h20 industry-relative Q5-Q1 |
| --- | ---: | ---: |
| INDUSTRY_PRESSURE | -0.406% | -1.027% |
| INDUSTRY_NONPRESSURE | -0.244% | -0.474% |
| BROAD_MARKET_PRESSURE | -0.347% | -0.858% |
| early_2018_2021 | -0.412% | -0.760% |
| late_2022_2023 | -0.400% | -1.331% |

## Year-by-year h20 industry-pressure spread

| Year | Q5-Q1 net | Q5-Q1 industry-relative |
| --- | ---: | ---: |
| 2018 | -1.091% | -1.214% |
| 2019 | -0.769% | -0.564% |
| 2020 | +0.013% | -0.183% |
| 2021 | -1.295% | -1.352% |
| 2022 | -1.896% | -1.831% |
| 2023 | -0.754% | -0.752% |

## Confound and Strategy-A independence audit

Generic-RS same-date rank correlation is 0.566; Low-MAX correlation is -0.059. Champion overlap among primary Q5 pressure observations is 0.28%. No Strategy-A rule or result was modified.

| Control | h20 tercile spreads (Q5-Q1 industry-relative) |
| --- | --- |
| GENERIC_RS | -0.260% / -0.240% / -0.391% |
| REALIZED_VOLATILITY | -0.539% / -1.267% / -1.472% |
| LIQUIDITY | -1.100% / -1.196% / -1.058% |
| LOW_MAX | -0.686% / -1.209% / -1.122% |

## Defensive versus Alpha diagnosis

At h20, Q5-Q1 net return is -1.019%, industry-relative spread is -1.027%, severe-loss change is -0.082%, and MAE change is +0.060%. The classification follows positive Alpha and incrementality, not loss avoidance alone.

## Decision and next direction

`NULL`. Do not rescue this formulation; re-rank independent Alpha frontiers.

This is consumed 2018–2023 development evidence, not OOS confirmation. Post-2023 outcome rows and CY-011 were not read.
