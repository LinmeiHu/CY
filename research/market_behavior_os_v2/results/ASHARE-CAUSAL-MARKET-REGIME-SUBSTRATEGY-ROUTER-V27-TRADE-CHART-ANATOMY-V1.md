# V27 trade-chart anatomy V1

## Scope

This is post-hoc development anatomy of the frozen V27 strategy. All 809 accepted trades with signal dates from 2014 through 2020 were reviewed chronologically and again by complete outcome group. No 2021+ trade outcome was used to form the rule.

Reviewed material:

- 90 chronological contact sheets covering 809/809 trades;
- 59 winner sheets covering all 526 trades with net return at least 4%;
- 9 small-profit sheets covering all 74 trades from 0% through 4%;
- 16 ordinary-loss sheets covering all 144 trades between -10% and 0%;
- 8 severe-loss sheets covering all 65 trades at or below -10%.

## What the charts show

The stable separator is a path, not a named candlestick.

1. Most target winners establish visible upside progress within roughly two to five valid sessions. They either move away from the entry coordinate or at least reach a material fraction of the frozen target.
2. Severe losers usually do not collapse immediately. The common sequence is a small or noisy rebound, little target progress, then repeated closes below the entry coordinate before the larger loss develops.
3. A single close below entry cost is not a failure signal. Many profitable mean-reversion trades first dip below cost and then recover.
4. A first positive candle is not confirmation. Numerous eventual losers show an initial false rebound.
5. A generic day-1 or day-3 time stop is too aggressive. Some genuine winners start slowly, particularly time-stop winners that finish between roughly 4% and 9%.

Visible corporate-action/gap discontinuities also show why the rule must use accepted action-coordinate prices rather than raw chart levels.

## Compressed candidate

Only one rule survived contradiction review:

> At the close of the fifth valid session including the entry session, exit on the next legal open only when (a) the trade has never reached half of its already-frozen 10%/15% target and (b) both the fourth and fifth valid-session closes are below the executed entry coordinate.

The economic interpretation is failed demand follow-through: the expected rebound has made no meaningful progress and sellers have kept the stock below the buyer's cost for two consecutive closes.

This joint condition is deliberately narrower than either component. Winner charts provide direct counterexamples to each component alone.

## Known contradiction

Some slow-starting winners also satisfy visually similar early weakness and later recover. Therefore the rule is not accepted from chart inspection alone. It has been frozen before aggregation and receives one development replay with no threshold, day-count, lane, or target rescue.

## One-shot development replay

The contradiction was economically decisive. The frozen rule triggered and executed on 249 of 809 trades.

| Metric | Frozen V27 | D5 failure exit | Change |
|---|---:|---:|---:|
| Mean net return per trade | 4.53% | 3.07% | -1.46 pp |
| Median net return per trade | 9.60% | 6.04% | -3.56 pp |
| Win rate | 74.17% | 57.73% | -16.44 pp |
| At least 4% profit | 65.02% | 52.29% | -12.73 pp |
| Severe loss (<= -10%) | 8.03% | 5.32% | -2.72 pp |
| Mean holding sessions | 13.40 | 9.61 | -3.79 |
| Portfolio total return | 28.30% | 16.21% | -12.09 pp |
| Portfolio CAGR | 3.60% | 2.15% | -1.44 pp |
| Portfolio maximum drawdown | -3.31% | -3.11% | +0.20 pp |
| Portfolio Sharpe | 1.22 | 0.92 | -0.30 |

The exit avoided 36 baseline severe losses but sacrificed 103 baseline trades that had ultimately earned at least 4%. It turned 134 originally profitable trades negative. Among the 249 affected trades, 69 improved and 180 deteriorated; their mean return change was -4.75 percentage points.

The damage appeared in every lane. Only 2016 had a negligible positive change in mean trade return (+0.03 pp), while every other development year lost mean return. Portfolio drawdown improved by only 0.20 percentage point because fixed membership left the released capital idle; that conservative treatment cannot explain the much larger loss of trade expectancy.

## Decision

`CLOSED_DEVELOPMENT_RULE_FAILED_NO_RESCUE`

The chart pattern is real as downside-risk information but not sufficiently specific for a dynamic exit. Slow-starting winners and developing losers overlap too heavily during the first five sessions. Changing the day count, half-target threshold, number of below-cost closes, or applying the rule only to the best-looking lane would be an outcome-driven rescue and is prohibited.

The useful lesson is narrower: complete chart review can identify a risk motif without producing a profitable trading rule. V27 should not receive another early cost-loss exit search. The next return-seeking work should start from a broader, economically distinct mother signal with enough annual event recall rather than attempt to extract more annualized return from these 809 already-selected entries.

Frozen rule specification SHA-256: `5f581a37aa4ef343c5c3a3372bc6b2ab22d11e2099f546d6d8b91f4197560996`.

Compact result SHA-256: `fc04f0439b890e592d2d9ba5dd3078bde9f6962bfcb642a2df7063454678e135`.
