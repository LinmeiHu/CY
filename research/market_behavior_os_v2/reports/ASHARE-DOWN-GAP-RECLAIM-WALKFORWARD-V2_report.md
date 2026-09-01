# ASHARE-DOWN-GAP-RECLAIM-WALKFORWARD-V2

**Development verdict: `MARGINAL_WALK_FORWARD_EDGE`**

The frozen expanding selector does not justify Validation. Main Board earned only 1.48% over five test years (0.29% CAGR, 0.118 Sharpe) and lost money in four of five years. ChiNext lost 1.47%. The fixed 50/50 portfolio was economically flat and all meaningful gains came from 2020 panic-repair conditions.

## Frozen contract and chronology

Spec SHA-256: `a030ce4d7d3051b4cdad328c51634436f48c3516a2c059ec5b0433abf07e0f80`. The candidate grid contains 8,748 configurations per board and 17,496 per fold. Selection maximizes training Calmar after the 100-total/20-recent-year trade gate, with the frozen deterministic tie-breaks.

Development is 2014–2021. Walk-forward test years are 2017–2021. Validation 2022–2023 and Final OOS 2024+ remain sealed and unread.

## MAIN

Stitched 2017–2021: total 1.48%, CAGR 0.29%, max drawdown -5.06%, Sharpe 0.118, Calmar 0.058, trades 224. Baseline total -99.77%, CAGR -70.17%, Sharpe -6.506.

| Test year | Champion | Train Calmar | Test return | Max DD | Sharpe | Trades | Top-10 median | Top-10 profitable |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `g0.09|a3|d0.50|cN|bQ90|xT1_CLOSE|k50|rDRYUP` | 3.397 | -0.95% | -0.95% | -1.660 | 12 | -0.95% | 0% |
| 2018 | `g0.07|aU|d0.50|cN|bNONE|xT1_CLOSE|k50|rGAP` | 1.870 | -3.85% | -4.29% | -1.840 | 119 | -2.61% | 0% |
| 2019 | `g0.09|a3|d0.50|cN|bQ90|xT1_CLOSE|k50|rDRYUP` | 1.882 | -0.20% | -0.89% | -0.297 | 16 | -0.20% | 0% |
| 2020 | `g0.07|a3|d0.50|cN|bQ90|xT1_CLOSE|k50|rDRYUP` | 1.465 | 7.20% | -1.02% | 1.226 | 70 | 7.22% | 100% |
| 2021 | `g0.09|a3|d0.50|cN|bQ90|xT1_CLOSE|k50|rDRYUP` | 1.567 | -0.40% | -0.40% | -0.982 | 7 | -0.40% | 0% |

Yearly returns: {'2017': -0.00951668916447257, '2018': -0.038467549204937224, '2019': -0.002034632628652111, '2020': 0.07200530872925137, '2021': -0.003975718926275684}. Parameter stability: `MODERATELY_ADAPTIVE`. Selected sequences: `{'gap_min': [0.09, 0.07, 0.09, 0.07, 0.09], 'age_max': [3, -1, 3, 3, 3], 'dryup_max': [0.5, 0.5, 0.5, 0.5, 0.5], 'compression_max': [-1.0, -1.0, -1.0, -1.0, -1.0], 'breadth_regime': [2, 0, 2, 2, 2], 'exit_code': [1, 1, 1, 1, 1], 'k': [50, 50, 50, 50, 50], 'ranker': [1, 0, 1, 1, 1]}`.

Concentration: top day 28.23%, top five days 53.03%, top 1% days 68.87%; excluding best day -3.30%, excluding best five days -7.50%.

Opening-gap breadth diagnostics: `{'>=Q90': {'trades': 146, 'pnl': 0.03601998970620675, 'average_trade_return': 0.01375361272405331, 'win_rate': 0.541095890410959}, 'Q75-Q90': {'trades': 48, 'pnl': -0.007149578250286774, 'average_trade_return': -0.007660536223044673, 'win_rate': 0.4583333333333333}, 'below Q75': {'trades': 30, 'pnl': -0.014040077524008557, 'average_trade_return': -0.023981406251810177, 'win_rate': 0.36666666666666664}}`.

ST diagnostics: `{'NON_ST': {'trades': 224, 'pnl': 0.01483033393191141, 'average_trade_return': 0.0041110693368363125}}`.

## CHINEXT

Stitched 2017–2021: total -1.47%, CAGR -0.29%, max drawdown -9.84%, Sharpe -0.081, Calmar -0.030, trades 482. Baseline total -94.98%, CAGR -44.83%, Sharpe -3.322.

| Test year | Champion | Train Calmar | Test return | Max DD | Sharpe | Trades | Top-10 median | Top-10 profitable |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2017 | `g0.09|a10|dN|cN|bQ90|xT1_OPEN|k50|rDRYUP` | 1.168 | -1.04% | -1.04% | -2.467 | 13 | -1.04% | 0% |
| 2018 | `g0.09|a3|dN|cN|bQ75|xT1_OPEN|k50|rDRYUP` | 0.679 | -5.32% | -5.47% | -2.395 | 185 | -5.31% | 0% |
| 2019 | `g0.09|aU|dN|cN|bQ90|xT1_OPEN|k50|rDRYUP` | 0.594 | -3.51% | -3.88% | -2.493 | 75 | -3.05% | 0% |
| 2020 | `g0.09|a3|dN|cN|bQ90|xT1_OPEN|k50|rDRYUP` | 0.398 | 8.99% | -1.25% | 1.404 | 209 | 8.99% | 100% |
| 2021 | `g0.09|aU|d0.50|cN|bQ90|xT1_CLOSE|k20|rGAP` | 0.546 | 0.00% | 0.00% | 0.000 | 0 | 0.00% | 0% |

Yearly returns: {'2017': -0.010427793227456572, '2018': -0.05323104488708008, '2019': -0.03513830721955258, '2020': 0.08994598487942906, '2021': 0.0}. Parameter stability: `MODERATELY_ADAPTIVE`. Selected sequences: `{'gap_min': [0.09, 0.09, 0.09, 0.09, 0.09], 'age_max': [10, 3, -1, 3, -1], 'dryup_max': [-1.0, -1.0, -1.0, -1.0, 0.5], 'compression_max': [-1.0, -1.0, -1.0, -1.0, -1.0], 'breadth_regime': [2, 1, 2, 2, 2], 'exit_code': [0, 0, 0, 0, 1], 'k': [50, 50, 50, 50, 20], 'ranker': [1, 1, 1, 1, 0]}`.

Concentration: top day 18.74%, top five days 55.39%, top 1% days 75.93%; excluding best day -5.27%, excluding best five days -12.70%.

Opening-gap breadth diagnostics: `{'>=Q90': {'trades': 415, 'pnl': 0.016354966088933096, 'average_trade_return': 0.002428527399809545, 'win_rate': 0.4819277108433735}, 'Q75-Q90': {'trades': 67, 'pnl': -0.031070721617037233, 'average_trade_return': -0.02433906718746765, 'win_rate': 0.2835820895522388}}`.

ST diagnostics: `{'NON_ST': {'trades': 482, 'pnl': -0.014715755528104127, 'average_trade_return': -0.001292279316679193}}`.

## Fixed 50/50 combined

Total 0.01%, CAGR 0.00%, max drawdown -7.44%, Sharpe 0.013, Calmar 0.000.

Yearly returns: {'2017': -0.009972241195964626, '2018': -0.04584590040364678, '2019': -0.018450801622198254, '2020': 0.08075086439252788, '2021': -0.002021182993194426}. Top day share 25.01%; top five 53.88%; top 1% 70.18%; return excluding best day -4.28%.

## Mechanism and stopping decision

Large, fresh, dry pre-reclaim gaps and Q90 opening-panic states were repeatedly selected on Main Board; ChiNext consistently selected 9% gaps and mostly Q90 breadth. Compression never survived selection. The only profitable test year for either sleeve was 2020, while every fold's top-10 neighborhood was uniformly losing in 2017–2019 and uniformly profitable only in 2020; 2021 produced a small Main loss and no ChiNext trades. This is regime-specific historical description, not reliable next-year translation.

`IS_STRATEGY_READY_FOR_2022_2023_VALIDATION = NO`. Close V2 at Development and retain the opening-panic/fresh-gap/dry-up representation only as an unproven research representation; do not open Validation as a rescue.

## Correctness audit

`{'test_year_used_in_own_parameter_selection_count': 0, 'test_year_breadth_used_to_set_own_threshold_count': 0, 'post_signal_feature_leakage_count': 0, 'post_2021_outcome_read_count': 0, 'duplicate_position_entry_count': 0, 'max_concurrent_positions_violation_count': 0, 'negative_cash_or_leverage_violation_count': 0, 'cross_board_parameter_contamination_count': 0, 'cross_board_breadth_calibration_count': 0, 'validation_opened': False, 'final_oos_opened': False}`

Validation 2022–2023 and Final OOS remain sealed and unread.
