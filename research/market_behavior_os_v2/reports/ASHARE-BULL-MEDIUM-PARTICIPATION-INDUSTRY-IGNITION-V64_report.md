# ASHARE-BULL-MEDIUM-PARTICIPATION-INDUSTRY-IGNITION-V64

`BULL_MEDIUM_PARTICIPATION_INDUSTRY_IGNITION_TARGET_MET`

Evidence label: `ITERATIVE_2014_2023_RESEARCH_NOT_PRISTINE_VALIDATION`.

|Year|Trades|Mean net|Median net|Date-equal mean|Win|Severe10|Mean hold|
|---:|---:|---:|---:|---:|---:|---:|---:|
|2014|178|3.08%|2.19%|2.82%|60.67%|3.93%|16.174157303370787|
|2015|100|8.78%|11.43%|7.90%|86.00%|2.00%|17.23|
|2016|125|2.32%|1.17%|1.74%|57.60%|4.00%|17.04|
|2017|76|3.87%|2.23%|3.80%|59.21%|1.32%|14.289473684210526|
|2018|11|-2.37%|-1.95%|-2.37%|27.27%|9.09%|16.0|
|2019|146|5.99%|8.04%|5.12%|67.12%|4.11%|12.102739726027398|
|2020|161|2.16%|2.71%|-1.46%|53.42%|18.63%|12.84472049689441|
|2021|115|4.47%|3.95%|4.21%|65.22%|2.61%|13.365217391304348|
|2022|38|0.95%|1.00%|1.30%|55.26%|15.79%|14.105263157894736|
|2023|136|2.10%|0.64%|1.58%|52.94%|2.94%|14.198529411764707|

Gate: `{"2021_2023_each_date_equal_positive": true, "2021_2023_each_positive": true, "capacity_accepted_completed_gt_500": true, "mean_excluding_best5_dates_positive": true, "mean_holding_lt_15": true, "mean_net_gt_3pct": true, "top5_date_positive_pnl_share_le_25pct": true}`.

V64 distinguishes a short breadth rebound from a medium-term bull participation state, then requires a PIT industry breadth ignition and an underextended first controlled pressure break.

## Frozen simple rule

The signal is deliberately distinct from collapse-gap repair. It requires all of the following at the completed daily signal close:

1. Medium-term participation: market breadth20 >= 65%, market breadth60 >= 45%, and market return20 > -3%.
2. Industry ignition: industry return20 > 3%, industry breadth20 > 60%, industry return20 five-session acceleration >= 3 percentage points, and industry breadth20 five-session acceleration >= 25 percentage points.
3. Underextended first pressure break: stock return60 is between 0% and 15%, there was no limit-up in the prior 20 completed sessions, and the completed close exceeds the prior completed 20-session high.
4. Controlled demand: signal-day return is between 2% and 6%, close location >= 70%, and turnover is 1.5x–4.0x its prior-20-session mean.

Entry is the first legal daily open within three sessions after the signal. The standing target is +15% from entry, first sellable on T+1; otherwise the position exits at the next legal open after H15. Round-trip cost is 40 bp. The portfolio is two isolated 50% sleeves (Main and ChiNext), K30 per sleeve, at most 10 new positions per sleeve per date, with no leverage or cross-sleeve transfer.

## Aggregate and board results

- Capacity-accepted completed trades: 1,086 (108.6 per year); capacity skips: 1,017.
- Mean / median net trade return: 3.72% / 3.29%; win rate: 61.33%; target hit: 29.28%; severe-loss10: 5.99%.
- Mean holding: 14.58 exchange-session indices. H15 exits can exceed 15 calendar-session indices when legal exit is delayed; the median is 16 indices because the signal session is included in the stored index convention.
- Main: 766 trades, 3.28% mean, 2.64% median, 60.18% win, 6.53% severe10, 15.17 mean holding.
- ChiNext: 320 trades, 4.78% mean, 5.20% median, 64.06% win, 4.69% severe10, 13.16 mean holding.
- Portfolio: 92.56% total return, 6.89% CAGR, -10.79% MaxDD, 1.275 Sharpe, 10.87% average utilization.

There are 904 unique securities and 104 PIT industries. Exact symbol/signal-date overlap is only 8 trades with preserved V24 and 10 with preserved V26, so this is economically and operationally complementary rather than a relabeling of either strategy.

## Concentration and chronology

- 210 unique signal dates; largest date contributes 1.84% of trades.
- Mean net return after removing the best five signal dates remains +2.99%.
- The best five signal dates contribute 21.12% of positive trade PnL, below the frozen 25% cap.
- 2021, 2022, and 2023 trade means and signal-date-equal means are all positive.
- 2018 is a sparse negative year (11 trades, -2.37% mean). In 2020 the event-weighted mean is +2.16%, but the date-equal mean is -1.46% and severe-loss10 is 18.63%. These are retained stability warnings, not post-hoc exclusions.

The development-only 2014–2020 subset has 797 accepted trades, +4.02% mean, +3.97% median, and 14.84 mean holding. It passes the same >500-trade, >3%-mean, <15-session, positive-ex-best-five-dates, and six-positive-years gates before the 2021–2023 robustness block.

## Causality and execution audit

All recorded audit counts are zero: feature/availability after decision, post-2023 signal or feature use, signal-bar fills, T+1 same-day exits, entry after the three-session window, invalid corporate-action coordinate lineage, hard-valid failures, duplicate events, cost-identity drift, profile drift, K violations, and negative cash. Repository 2024+ signals and features were not opened.

## Interpretation

The economic hypothesis is that a broad, already-participating market plus sharply improving PIT industry breadth creates a short-lived demand expansion. Requiring an underextended stock's first controlled pressure break seeks participation before the stock becomes crowded or parabolic. The rule uses four interpretable condition families and no fitted model.

This is iterative 2014–2023 research, not pristine external validation. The pooled target is met, but the sparse 2018 failure and 2020 date-level weakness mean the result should be preserved as a promising complementary strategy rather than treated as unconditional proof of a universal bull-market edge.
