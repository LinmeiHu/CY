# ASHARE-CAUSAL-BEAR-STRONG-BULL-DUAL-ENGINE-V17

`DUAL_ENGINE_PASSES_DEVELOPMENT_GATE`

## Simple routed strategy

1. In causal BEAR, trade the frozen fast-capitulation active-demand engine only when breadth is improving.
2. In causal STRONG_BULL, require median stock ret60 >=5% and positive-ret60 breadth >=60%, then trade the frozen quiet-inventory breakout only after its third-session platform acceptance.
3. In weak BULL and TRANSITION, hold cash.
4. Both engines enter only at a later legal open, target +20%, time-exit after H60, use no stop, and charge 40 bp round trip.

Every state input is known at or before the relevant completed decision close. No future return labels the market state.

## Development 2014-2020

Trades 680 (97.1/year); mean 7.50%; median 19.60%; win 66.91%; severe10 18.82%.

|Year|Trades|Mean net|Median net|Win|Severe10|
|---:|---:|---:|---:|---:|---:|
|2014|44|6.88%|19.60%|65.91%|25.00%|
|2015|125|15.39%|19.60%|90.40%|6.40%|
|2016|71|6.41%|15.26%|59.15%|19.72%|
|2017|32|4.86%|3.96%|65.62%|18.75%|
|2018|147|1.44%|0.85%|51.70%|25.85%|
|2019|107|13.44%|19.60%|80.37%|11.21%|
|2020|154|3.98%|4.93%|57.14%|25.32%|

## Scientific status

This is a post-hoc development combination. It can authorize an outcome-blind 2024 identity freeze, but cannot itself be called independent confirmation.
