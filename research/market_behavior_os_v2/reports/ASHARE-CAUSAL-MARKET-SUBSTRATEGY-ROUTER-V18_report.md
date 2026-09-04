# ASHARE-CAUSAL-MARKET-SUBSTRATEGY-ROUTER-V18

`CAUSAL_MARKET_SUBSTRATEGY_ROUTER_HISTORICAL_GOAL_MET`

## Correction to V16

V16 treated every causally positive broad market as suitable for the same
continuation strategy.  That was too coarse.  A market can remain positive on
a 60-session basis while the recent 20-session advance is already
decelerating.  In that state a stock breakout has less broad continuation
support.

V18 therefore routes at the completed signal-session close:

- **BEAR_REPAIR:** exact frozen V13R1 fast-capitulation active-demand T10/H20;
- **BULL_ACCELERATING:** exact frozen V15 delayed supply-contraction T10/H20,
  but only when `market_median_ret20 >= market_median_ret60`;
- **BULL_DECELERATING:** cash;
- **TRANSITION:** cash.

The gate uses cross-sectional returns known at the completed signal close.  It
does not classify the market from a future index return.

## Development selection

Seven bounded and economically interpretable bull-state candidates were
compared only on 2014–2020.  Return acceleration ranked first with 55 trades,
+3.72% mean net return, 72.73% win rate, and 12.64 sessions average holding.
No 2021–2023 row entered this selection calculation.

The 2021–2023 chronology is a post-observation diagnostic, not pristine
validation, because these outcomes had already been seen in predecessor work.

## V16 versus V18

| Metric | V16 | V18 |
|---|---:|---:|
| Trades, 2014–2023 | 806 | 630 |
| Average trades/year | 80.6 | 63.0 |
| Mean net trade | +3.176% | **+3.485%** |
| Win rate | 70.47% | **71.11%** |
| Severe loss <= -10% | 12.53% | **10.95%** |
| Average holding | 12.86 | 13.09 |
| 2021–2023 mean net | +2.626% | **+3.296%** |
| 2022 mean net | +3.742% | **+4.836%** |
| 2023 mean net | +1.743% | **+3.871%** |
| Total portfolio return | +21.17% | +15.78% |
| Portfolio CAGR | +1.94% | +1.48% |
| Max drawdown | -4.00% | -3.96% |

Trade quality and the weak-year diagnostics improve, but total portfolio
return falls because the router deliberately holds more cash.  Average capital
utilization declines from 4.06% to 2.99%.

## Why 2022–2023 improve

| Year | Bull state | Trades | Mean net |
|---|---|---:|---:|
| 2022 | accelerating, admitted | 2 | +6.15% |
| 2022 | decelerating, cash | 14 | -5.09% counterfactual |
| 2023 | accelerating, admitted | 7 | +4.32% |
| 2023 | decelerating, cash | 5 | -8.90% counterfactual |

The bear-repair lane remained positive in both years: +4.81% on 111 trades in
2022 and +3.70% on 18 trades in 2023.  The former weakness was therefore a
routing error inside the positive-market state, not a failure of the bear
mechanism.

## Historical evidence

| Year | Trades | Mean net | Win | Severe10 | Avg hold |
|---|---:|---:|---:|---:|---:|
| 2014 | 15 | +2.15% | 60.00% | 13.33% | 15.27 |
| 2015 | 73 | +7.77% | 89.04% | 2.74% | 11.34 |
| 2016 | 62 | -0.18% | 59.68% | 30.65% | 11.84 |
| 2017 | 35 | +1.81% | 60.00% | 5.71% | 18.43 |
| 2018 | 149 | +3.19% | 68.46% | 11.41% | 15.05 |
| 2019 | 13 | +5.85% | 76.92% | 0.00% | 10.31 |
| 2020 | 44 | +4.63% | 84.09% | 11.36% | 12.27 |
| 2021 | 101 | +1.43% | 58.42% | 13.86% | 12.86 |
| 2022 | 113 | +4.84% | 80.53% | 6.19% | 11.21 |
| 2023 | 25 | +3.87% | 68.00% | 4.00% | 13.20 |

The pooled requested gates pass: 63 trades/year, +3.485% mean net, and 13.09
sessions average holding.  This is not a claim that every year passes.  The
2016 loss and low counts in 2014, 2019, and 2023 remain limitations.

## Causality and execution audit

All required counts are zero:

- market feature timestamp after signal decision;
- challenge row used in 2014–2020 selection;
- missing market input or accepted bull row failing acceleration;
- source-lane PIT, breadth-repair, setup, or first-breakout violation;
- entry at/before signal, same-day exit, or impossible execution;
- corporate-action coordinate-lineage violation;
- duplicate active symbol, leverage, or negative cash;
- post-2023 signal or outcome access.

Repository 2024+ data were not opened in this experiment.

## Interpretation

V18 supports the user's mechanism: market state should route strategy choice.
The same stock pattern is admitted in an accelerating broad bull market and
rejected in a decelerating positive market.  This improves 2022 and 2023, but
the result remains post-observation development and requires a newly arriving,
untouched period before any deployment claim.
