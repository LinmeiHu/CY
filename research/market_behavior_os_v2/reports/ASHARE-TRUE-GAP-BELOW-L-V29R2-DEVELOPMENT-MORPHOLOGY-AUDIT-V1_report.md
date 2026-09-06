# ASHARE-TRUE-GAP-BELOW-L-V29R2-DEVELOPMENT-MORPHOLOGY-AUDIT-V1

Strictly read-only development audit. Every opened market-data partition is 2018-2021; maximum signal, entry, exit, chip, and minute observation dates are no later than 2021-12-31. No validation title or return source is opened.

## Universe

- All 355 executable V28R2 outcomes; V29R1's 298 executable outcomes are an exact subset.
- Baseline: mean +6.39%, median +6.37%, win 93.5%, mean holding 7.89 sessions.
- Signal years: {2018: 298, 2019: 23, 2020: 10, 2021: 24}.
- Winners/losers are 332/23. The analysis does not fit on the 14 portfolio losers or the two issuer-title cases.
- Latest PIT chip is missing for 32/355 signals and is left missing. No substitute, normalization, or clipping is used.

## Signal-close features

The clearest full-sample monotone relationship is excessive one-day stock outperformance versus the market. Mean return by ascending quartile is +7.31% / +6.88% / +6.22% / +5.14%; the upper quartile also has materially lower hit rate and longer holding. Turnover ratio is directionally monotone in mean return, but its separation is weaker. Distances to support/L and PIT chip p10/p50 are not jointly monotone enough to justify a cutoff.

Simplest development candidate: **signal-day stock return minus the cross-sectional market median must be <= 2 percentage points**. This is a non-chasing condition known at the signal close, so the existing T+1-open chronology remains legal.

- Pass: n=265 (66.25/year), mean=+6.82%, median=+6.42%, win=97.4%, mean hold=6.82.
- Fail: n=90, mean=+5.12%, median=+6.26%, win=82.2%, mean hold=11.07.
- Annual pass profile:
- 2018: n=232, mean=+6.97%, win=98.7%, mean hold=6.55
- 2019: n=16, mean=+4.86%, win=87.5%, mean hold=9.38
- 2020: n=7, mean=+8.24%, win=85.7%, mean hold=11.14
- 2021: n=10, mean=+5.34%, win=90.0%, mean hold=5.90

This is post-hoc and highly imbalanced toward 2018. The small 2019-2021 counts prevent calling it validated; it is only the simplest candidate for a new frozen development experiment.

There are only 56 unique signal dates and the largest date contributes 145 rows. With each signal date weighted equally, pass dates average +5.26%; on the 19 dates containing both groups, pass minus fail averages +1.93% and is positive on 57.9% of dates.

## T+1 first 30 minutes

All 355 entries have exactly six hard-valid registered five-minute windows, and the last observation is available at 10:00. First-30-minute VWAP quartile mean returns are +5.35% / +6.75% / +6.52% / +6.92%, with the lowest quartile carrying the weakest hit rate and longest holding.

Descriptive 10:00 demand condition: **10:00 close >= first-30-minute VWAP**.

- Association among frozen open-entry outcomes, pass: n=254, mean=+6.82%, win=96.1%, mean hold=6.99.
- Fail: n=101, mean=+5.30%, win=87.1%, mean hold=10.16.

Equal-date weighting gives +6.48% for pass dates. Among 11 signal dates containing both pass/fail observations, pass minus fail averages +2.32% and is positive on 81.8% of dates.

This is not an executable return estimate. CY-008 ends at the bar whose value becomes known at 10:00 and contains no post-decision fill bar. Any use requires a separately registered 10:00-after entry procedure, with the earliest legal fill after 10:00 and all exits recomputed from that price. It cannot be attached to the frozen opening fill.
