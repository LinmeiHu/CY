# V29 robustness and mechanism audit

## Scope

This is a deterministic diagnostic of the already frozen
`ASHARE-SIMPLE-REGIME-COMPLEMENTARY-DEMAND-ROUTER-V29` result. It does not add
or select a rule, threshold, target, holding period, rank, or portfolio choice.

The intended economic sequence is:

1. completed market data identify a Bear or broad-participation Bull state;
2. the market state selects one of three independent stock mechanisms;
3. a completed daily demand event creates the signal;
4. entry is the first legal open strictly after the signal;
5. the fixed target or time stop closes the trade under QD-010 and T+1.

The three mechanisms are:

- `BEAR_WORSENING_FAST_CAPITULATION`: forced selling followed by active demand;
- `BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION`: broad weakness is stabilizing and
  stock-specific fresh supply has contracted;
- `SIMPLE_BULL_PARTICIPATION_IGNITION`: broad participation plus PIT industry
  ignition, in an underextended stock making a controlled first pressure break.

## Why the two preceding attempts failed

`V5` compressed same-day price and turnover state into a scorecard. Its pooled
gains depended on sparse later T15 realizations; the first one to three sessions
did not show stable absolute alpha. The failure was therefore not a ranking bug
but a mismatch between a broad state score and the short-horizon economic event.

`V6` added next-session overnight acceptance. It reduced some adverse tails but
did not create positive continuation. Acceptance was a risk descriptor, not a
new source of demand. Increasing model capacity or adding more acceptance
thresholds would not repair that missing mechanism.

V29 therefore does not combine V5 and V6. It routes three different mechanisms
using causally known market state and compresses the Bull mechanism to five
semantic condition groups.

## Frozen simple Bull conditions

1. market breadth over 20 sessions is at least 65%;
2. industry return is above 3%, industry breadth is above 60%, and its
   five-session breadth change is at least 25 percentage points;
3. stock 60-session return is between 0% and 15%, with no prior-20 upper-limit
   close;
4. the completed signal close is above the known prior-20 high, the signal-day
   return is between 2% and 6%, and close location is at least 70%;
5. signal turnover is 1.5 to 4.0 times the prior-20 mean.

The same-symbol cooldown is 21 market sessions. No alternate value was tested
inside V29. The two Bear source detectors and their Bear substate routing are
the exact frozen V27 definitions; V29 did not simplify or alter their internal
conditions.

## Historical target check

For 2014-2025, after shared K30-per-board capacity:

- completed trades: 2,721;
- average completed trades per full year: 226.75;
- pooled mean net trade return: +3.1581%;
- pooled median net trade return: +3.4180%;
- signal-date-equal mean: +2.3904%;
- win rate: 62.33%;
- severe-loss10: 7.64%;
- every full calendar year has positive mean trade return;
- every full calendar year has positive portfolio return.

The fresh 2026 YTD slice has 177 trades, +2.4932% event-weighted mean, and
-0.9190% signal-date-equal mean. It therefore confirms positive average trade
economics but exposes a date-clustering weakness; this slice was not used for a
post-hoc filter.

## Route chronology

The table below reports accepted trade count and mean net return by source.

| Year | Bear N | Bear mean | Simple Bull N | Simple Bull mean |
|---:|---:|---:|---:|---:|
| 2014 | 12 | +2.74% | 211 | +3.02% |
| 2015 | 50 | +7.38% | 101 | +8.74% |
| 2016 | 77 | +2.00% | 136 | +2.59% |
| 2017 | 58 | +2.01% | 122 | +2.59% |
| 2018 | 165 | +5.41% | 112 | -0.57% |
| 2019 | 14 | +1.27% | 213 | +4.32% |
| 2020 | 44 | +3.37% | 179 | +2.26% |
| 2021 | 61 | +4.81% | 124 | +4.96% |
| 2022 | 106 | +3.99% | 145 | +0.50% |
| 2023 | 38 | +4.36% | 151 | +1.89% |
| 2024 | 152 | +2.55% | 159 | +3.32% |
| 2025 | 32 | +7.87% | 259 | +1.51% |
| 2026 YTD | 52 | +1.27% | 125 | +3.00% |

This is genuine mechanism complementarity rather than duplicated trades: the
cross-source same-symbol/same-date overlap count is zero. The Bull route fails
in 2018 and is weak in 2022 and 2025; the Bear route contributes most in those
states. Conversely, Bull participation supplies most observations in years
where accepted Bear opportunities are sparse.

## Leave-one-year-out concentration

Removing each full calendar year in turn leaves pooled event-weighted mean net
return between +2.8566% and +3.2784%. The corresponding signal-date-equal mean
stays between +2.0596% and +2.5245%. No single full year is required for the
pooled target.

Across all accepted observations:

- largest signal-date trade share: 0.72%;
- top-ten-symbol trade share: 1.86%;
- mean excluding the five best signal dates: +3.0738%;
- top-five signal dates' share of positive PnL: 9.31%.

The 2026 event mean remains +2.3706% after excluding its best signal date and
+2.0222% after excluding its five best signal dates. However, its date-equal
mean becomes still more negative after those removals. This identifies the
unresolved weakness as correlated bad signal dates, not dependence on one best
day.

## Board and portfolio diagnostics

Across 2014-2026 YTD:

| Board | Trades | Mean net | Median net | Win | Severe10 |
|---|---:|---:|---:|---:|---:|
| Main | 1,901 | +2.43% | +2.17% | 59.23% | 8.26% |
| ChiNext | 997 | +4.44% | +8.03% | 67.70% | 7.82% |

The chronological shared portfolio has +323.25% total return, 12.07% CAGR,
-10.00% maximum drawdown, 1.448 Sharpe, and 22.22% average utilization. All
calendar-year portfolio returns from 2014 through 2026 YTD are positive.

## Causality and execution audit

All of the following counts are zero:

- feature timestamp after decision;
- entry at or before signal;
- signal-bar fill;
- illegal entry open;
- illegal target or open exit;
- exit at or before entry;
- T+1 same-day exit;
- cost-identity mismatch;
- corporate-action coordinate-lineage violation;
- daily-path coverage mismatch or duplicate;
- target proceeds reused for an earlier same-day open;
- negative cash;
- K30 violation;
- threshold or rule change after outcome opening.

The outcome engine reproduced 3,543 overlapping frozen V65 rows with zero
categorical or numeric mismatch. V29 also consumes the hash-frozen V28 copy of
the V27 Bear source because the upstream Parquet was mechanically rewritten;
relevant row contents matched, but byte drift was handled fail-closed.

## Outcome-blind chart audit

The 36-page chartbook contains 12 deterministic event-ID samples from each of
the three mechanisms. Every page shows exactly 90 completed sessions before the
signal plus the signal bar, and ends at the signal close. It contains no entry,
exit, return, or post-signal bar. The book is therefore suitable for semantic
inspection without leaking outcomes into a subsequent interpretation.

## Scientific interpretation

V29 meets the frozen numerical goal and supplies an economically coherent
market-state router. It is not pristine external validation: the research lane
has seen many historical outcomes, and the Bull thresholds inherit the already
observed V65 neighborhood. The result should be described as an iterative,
multiple-testing-exposed causal historical candidate.

The largest unresolved risk is regime-date correlation: 2026 YTD has positive
event mean but negative date-equal mean and 15.25% severe-loss10. No 2026-derived
filter should be added. The defensible next action is to freeze V29 unchanged,
paper-run future signals, and judge a new untouched period with both
event-weighted and signal-date-equal criteria.
