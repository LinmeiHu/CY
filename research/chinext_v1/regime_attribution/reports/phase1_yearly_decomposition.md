# Phase 1 — why CHINEXT V1 years differ

> Zero-replay decomposition of 399 authoritative completed cycles and 1,942 daily NAV rows. No strategy signal, order, fill, NAV, or parameter was regenerated.

## Annual decomposition

| Year | Return | Max DD | Trades | Win | Mean / median trade | >=20% winners | <=-10% losses | Median MFE / MAE | Avg exposure | Top5 +P&L share | Ex-best5 return |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 | -3.78% | -4.65% | 11 | 18.18% | -3.47% / -3.47% | 0.00% | 9.09% | 2.76% / -4.04% | 2.88% | 100.00% | -3.78% |
| 2019 | 23.49% | -10.21% | 47 | 48.94% | 3.98% / -0.30% | 8.51% | 6.38% | 5.98% / -3.74% | 30.13% | 72.68% | -2.38% |
| 2020 | 5.27% | -20.76% | 74 | 47.30% | 1.66% / -0.32% | 9.46% | 16.22% | 9.41% / -4.64% | 33.74% | 43.48% | -12.01% |
| 2021 | 31.78% | -11.73% | 62 | 45.16% | 5.15% / -1.00% | 9.68% | 9.68% | 6.10% / -5.52% | 32.83% | 70.82% | -10.33% |
| 2022 | -17.29% | -17.96% | 37 | 13.51% | -4.89% / -5.12% | 0.00% | 13.51% | 3.35% / -6.95% | 10.74% | 100.00% | -19.65% |
| 2023 | 2.14% | -15.07% | 57 | 33.33% | 0.44% / -2.10% | 7.02% | 1.75% | 4.87% / -4.19% | 24.93% | 76.67% | -12.64% |
| 2024 | 49.05% | -23.54% | 38 | 31.58% | 15.11% / -2.62% | 26.32% | 18.42% | 6.37% / -5.55% | 23.59% | 77.43% | -7.43% |
| 2025 | 37.70% | -10.18% | 73 | 50.68% | 3.89% / 0.48% | 10.96% | 12.33% | 10.88% / -4.07% | 57.13% | 49.92% | 7.50% |

## FACT — first differing economics

- 2022 is the clearest failed year: 13.51% win rate, negative mean and median trade, no >=20% realized winner, and very weak MFE. Low exposure limited activity but did not create positive expectancy.
- 2024 is not a broad high-win-rate year. Its 49.05% portfolio return occurs with only a 31.58% win rate and a negative median trade; six >=50% cycles and a much stronger upper MFE tail create the result.
- 2025 is broader: the win rate and median trade turn positive, exposure is highest, and the Top5 share is materially lower than in 2024.
- 2019 and 2021 combine near-45–49% win rates with super-winners. 2020 has a similar win rate and seven 20–50% winners, but no >=50% winner, the second-highest severe-loss rate, and the only <=-20% loss before 2025; its positive tail is largely offset and drawdown is much larger.

## EVIDENCE — realized P&L buckets

| Year | >=50% P&L | 20–50% P&L | 0–20% P&L | 0 to -10% P&L | -10 to -20% P&L | <=-20% P&L |
|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 0 | 0 | 5,874 | -32,228 | -11,481 | 0 |
| 2019 | 160,154 | 67,320 | 114,960 | -113,705 | -64,581 | 0 |
| 2020 | 0 | 263,772 | 208,292 | -141,720 | -182,033 | -25,403 |
| 2021 | 526,611 | 49,654 | 167,331 | -214,855 | -129,740 | 0 |
| 2022 | 0 | 0 | 23,550 | -134,672 | -61,792 | 0 |
| 2023 | 0 | 108,842 | 50,586 | -133,217 | -8,518 | 0 |
| 2024 | 614,377 | 103,795 | 11,287 | -101,377 | -137,587 | 0 |
| 2025 | 238,989 | 353,621 | 309,153 | -239,840 | -161,801 | -51,463 |

## EVIDENCE — Top-N concentration

| Year | Top5 / 10 / 20 positive-P&L share | Ex-best5 / 10 / 20 portfolio return |
|---:|---:|---:|
| 2018 | 100.00% / 100.00% / 100.00% | -3.78% / -1.15% / 0.00% |
| 2019 | 72.68% / 90.22% / 99.46% | -2.38% / -8.62% / -11.91% |
| 2020 | 43.48% / 69.13% / 91.75% | -12.01% / -22.20% / -31.18% |
| 2021 | 70.82% / 88.10% / 97.82% | -10.33% / -20.60% / -26.38% |
| 2022 | 100.00% / 100.00% / 100.00% | -19.65% / -18.74% / -14.83% |
| 2023 | 76.67% / 94.11% / 100.00% | -12.64% / -16.00% / -17.08% |
| 2024 | 77.43% / 98.45% / 100.00% | -7.43% / -22.77% / -22.92% |
| 2025 | 49.92% / 72.27% / 92.38% | 7.50% / -6.02% / -18.19% |

## EVIDENCE — exposure, turnover, and drawdown window

| Year | Avg exposure | Return / avg exposure | Turnover | Return / turnover | Max-DD peak -> trough | Realized exit P&L in DD window | Severe-loss P&L in DD window |
|---:|---:|---:|---:|---:|---|---:|---:|
| 2018 | 2.88% | -1.316 | 2.17x | -0.017 | 2018-03-12 -> 2018-12-10 | -42,435 | -11,481 |
| 2019 | 30.13% | 0.780 | 10.71x | 0.022 | 2019-03-12 -> 2019-12-11 | 168,711 | -64,581 |
| 2020 | 33.74% | 0.156 | 14.12x | 0.004 | 2020-07-13 -> 2020-10-15 | 51,732 | -85,330 |
| 2021 | 32.83% | 0.968 | 12.71x | 0.025 | 2021-07-22 -> 2021-12-21 | 388,932 | -98,288 |
| 2022 | 10.74% | -1.609 | 7.28x | -0.024 | 2022-06-30 -> 2022-12-06 | -145,868 | -49,205 |
| 2023 | 24.93% | 0.086 | 11.48x | 0.002 | 2023-04-12 -> 2023-11-24 | -33,406 | 0 |
| 2024 | 23.59% | 2.079 | 8.74x | 0.056 | 2024-11-07 -> 2024-12-25 | 522,036 | -113,607 |
| 2025 | 57.13% | 0.660 | 16.30x | 0.023 | 2025-03-18 -> 2025-06-23 | 11,093 | -80,317 |

## EVIDENCE — exit and holding mechanism

| Exit lineage | Trades | Win rate | Median return | Realized P&L | Median hold | Median MFE / MAE |
|---|---:|---:|---:|---:|---:|---:|
| INDIVIDUAL_MA30_X2_AND_SET_REMOVAL | 95 | 25.26% | -6.11% | -523,617 | 12.0 | 6.16% / -8.18% |
| MARKET_EMERGENCY_X0.96 | 14 | 64.29% | 1.76% | 77,592 | 28.5 | 20.96% / -3.28% |
| MARKET_MA20_X2 | 283 | 44.88% | -0.74% | 1,931,557 | 8.0 | 6.07% / -4.04% |
| SET_REMOVAL | 7 | 14.29% | -5.52% | -53,376 | 7.0 | 9.40% / -7.29% |

Entry-month cohorts are diagnostic, not regimes. The five strongest and weakest realized-P&L cohorts were:

| Side | Entry month | Trades | Win rate | >=20% winners | <=-10% losses | Realized P&L |
|---|---|---:|---:|---:|---:|---:|
| BEST | 2024-09 | 10 | 100.00% | 9 | 0 | 706,394 |
| BEST | 2021-05 | 10 | 90.00% | 4 | 0 | 475,396 |
| BEST | 2019-02 | 9 | 88.89% | 3 | 0 | 247,357 |
| BEST | 2025-11 | 8 | 62.50% | 2 | 1 | 199,153 |
| BEST | 2020-06 | 12 | 58.33% | 4 | 1 | 155,533 |
| WORST | 2024-12 | 14 | 7.14% | 0 | 5 | -174,389 |
| WORST | 2021-11 | 13 | 15.38% | 0 | 3 | -118,175 |
| WORST | 2020-02 | 9 | 33.33% | 0 | 4 | -75,983 |
| WORST | 2022-08 | 12 | 0.00% | 0 | 3 | -75,735 |
| WORST | 2020-09 | 5 | 0.00% | 0 | 4 | -74,366 |

The machine artifact retains the complete annual exit tables, MFE/MAE, time-to-MFE, holding duration, giveback, and all entry/exit month cohorts. Individual/set-removal exits are descriptive lineage, not proof that the exit caused the loss.

Across-year rank correlations with annual portfolio return are descriptive only (n=8):

| Diagnostic | Spearman rho |
|---|---:|
| top_winner_rate_ge_20 | 0.970 |
| mean_trade_return | 0.929 |
| super_winner_rate_ge_50 | 0.862 |
| median_mfe | 0.786 |
| median_holding_days | 0.635 |
| median_trade_return | 0.571 |
| win_rate | 0.571 |
| average_invested_ratio | 0.548 |
| severe_loss_rate_le_neg10 | 0.333 |
| median_mae | 0.000 |

## INTERPRETATION

H-001 is supported at the yearly-decomposition level: changes in right-tail frequency/magnitude and favorable excursion explain more of the return ordering than the median trade alone. H-002 is also supported but qualified: bad years are not simply severe-loss years. The more fundamental failure is that ordinary losses are not offset by enough winners, while early/total favorable excursion is scarce.

Regime causality is not established here. Exposure is a transmission channel, not a sufficient explanation: 2018 had little exposure and a small loss; 2022 had low exposure and a large loss; 2024 generated a large gain with moderate exposure. Phase 2 must therefore measure the market opportunity state present at entry rather than infer it from annual labels.

## Important boundaries

- Calendar-year trade P&L is assigned by exit execution year. Entry-month cohorts are separate.
- Ex-best-N subtracts frozen realized completed-cycle P&L from the annual return denominator; it is a static concentration diagnostic, not a counterfactual NAV replay.
- When a year has fewer than N positive cycles, Top-N positive-P&L share saturates at 100%, while ex-best-N still removes the N highest-P&L cycles, including later-ranked losses. This makes some annual ex-best-N sequences non-monotone by construction.
- Maximum-drawdown trade attribution includes only cycles realized between the peak and trough. Unrealized marks also drive NAV drawdown, so that field is explicitly partial.
- MFE/MAE is the first-entry-open gross underlying total-return path, corporate-action adjusted, with the actual exit open as the only exit-session observation. Later rebalance cash flows do not redefine it.
- All three NAV blocks remain independent bounded PIT-B evaluations; no eight-year compounded NAV is claimed.

## Phase 1 verdict

**SUPPORTED:** right-tail availability and path persistence are the primary first-order differentiators. **SUPPORTED WITH QUALIFICATION:** win rate and ordinary-trade quality matter, particularly in 2022, but severe-loss frequency alone does not explain bad years. **UNRESOLVED:** which causal market states create or suppress those paths; this moves to the PIT feature audit.
