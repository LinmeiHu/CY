# ASHARE-BEAR-SLOW-SUPPLY-EXHAUSTION-12M-CHART-DISCOVERY-V2 review

## Scientific status

This is a post-screen development chart review. The causal-BEAR slow-supply-exhaustion lane was selected after its mother screen was known. It is neither an independent confirmation nor an untouched validation result.

The complete frozen chartbook was reviewed: 1,765 candidates, 213 review sheets, and all five fixed outcome classes. Charts use 126 completed market sessions before and after the signal where available. No signal after 2020 was used and the maximum plotted bar was 2021-06-30. No 2022-2024 signal or outcome was opened.

## What the charts repeatedly showed

1. **Signals were highly date-clustered.** The 1,757 completed trades came from only 233 signal dates. For example, 2018 contributed 901 completed trades but only 54 dates, while 2016 contributed 319 trades on 21 dates. Raw trade count therefore overstates independent evidence.
2. **Successful signals usually belonged to broad repair episodes.** Many winners appeared together when the cross-section stopped falling and demand broadened. The stock signal alone often looked very similar in successful and failed cases.
3. **Immediate platform acceptance mattered, but a mandatory next-day green candle did not.** Winners often paused or retested once before advancing. Requiring a particular next-day candle would discard valid cases and repeat the failed V19R1 confirmation mistake.
4. **Failed cases commonly lost the frozen prior-five-session high again.** A one-close failure was noisy; repeated closes below the level more often represented rejection rather than a normal retest.
5. **The original +10% target and bounded holding period remained economically important.** Many profitable charts later resumed their long decline. These were tactical repair trades, not evidence of durable trend reversal.

## Compressed causal rules

The following rules were fixed before the new outcome aggregation:

1. The signal must retain the exact frozen causal `BEAR` state. This uses only completed observations available by the signal close.
2. On that same signal date, the eligible A-share cross-section must show broad repair: median same-day return greater than zero and positive-return share greater than 0.50. Both quantities use only bars available by that close.
3. The stock must retain the exact frozen slow-supply-exhaustion mother definition; no stock threshold or lookback changes.
4. Entry remains the first legal open during t+1 through t+3. There is no same-bar fill and no mandatory next-day candle confirmation.
5. Exit remains +10% or H20, with one new deterministic failure exit: after entry, two consecutive valid closes below the signal-date frozen prior-five-session high trigger sale at the earliest subsequent legal open.

The two-close rule is deliberately coarse: it permits one ordinary retest and treats continued loss of the already-frozen platform as failed acceptance. There is no threshold grid, subset search, neighboring lookback, or rule rescue.

## Why this is economically different from earlier attempts

The market condition is not a future market-return label and not the old static BULL/BEAR split. It asks whether repair is already observable across the market at the decision close while the longer-horizon causal state remains bearish. The stock exit does not demand an optimized candle; it tests whether a pre-existing, signal-time price structure remains accepted after entry.

## Required evaluation

Evaluate once on the consumed 2014-2020 development period. Report trade counts and independent dates by year, pooled and annual economics, exit attribution, and comparison with the unchanged mother. The later-period gate requires more than 50 completed trades in every year, pooled mean net return above 4%, positive pooled median, and acceptable severe-loss incidence. Annual mean above 4% is reported separately as a stability diagnostic and is not silently substituted for the written gate.

