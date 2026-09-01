# V2 Timing Methodology and Outcome-Blind Freeze

This document freezes the V2 carrier and timing policy before the broad outcome-bearing run.
The choices below were made from V1 structure, contemporaneous OHLC semantics, causal
chronology, and economic interpretation—not from V2 forward returns.

## Frozen carrier

V1's deepest quintile was a full-sample ex-post feature percentile whose lower edge was a
60-session drawdown of approximately -30.67%. It remains a research-faithful reference only.
It is not silently treated as deployable.

The V2 causal deployable carrier is the already documented fixed deep region:

- the exact V1 LOW eligibility and lineage rules; and
- causal 60-session adjusted-close drawdown <= -30% at t0 close.

The -30% boundary was documented in V1 before V2 and closely maps the V1 Q5 region. It is not
selected or changed using V2 outcomes. An event is the first carrier observation after no
carrier observation in the prior 20 trading rows. All observations are retained only as a
supporting repeated-state view; the de-duplicated event cohort is primary.

## Frozen primary trigger

There is one trigger and no supporting-trigger tournament. During sessions t0+1 through
t0+5, inclusive, take the first day satisfying both:

1. `close > preclose` (a strictly positive reference-price session); and
2. `CLV = (close - low) / (high - low) >= 0.70`.

A zero-range day cannot trigger. The trigger is known only at that day's close. Entry is the
next listed session's open only when the inherited V1 legal-open rules accept it; there is no
same-close fill and no skipping to a later open after an rejected entry. The economic concept
is a simple, strong close-location recovery: price finishes in the top 30% of its range on a
positive day after the deep-oversold event.

The contemporaneous semantic sample contained no close outside `[low, high]`, CLV stayed in
`[0,1]`, and zero-range rows were explicit. No forward outcome was inspected during this
freeze.

## Frozen policies

- **Immediate:** t0 close signal, enter at the next legal listed-session open.
- **Fixed delay:** observe one full trading session after t0, then enter at the following
  legal listed-session open regardless of its price pattern.
- **Reversal wait:** scan the frozen five-session window for the first primary trigger and
  enter at the following legal listed-session open. No signal, or a rejected next-open entry,
  means cash with 0% event-policy return.

All policies start from the same t0 cohort. Common-horizon Ret20 exits every policy at t0's
adjusted close 20 trading sessions later. Entry-anchored trade-quality returns instead run
5/10/20 sessions from the policy's actual entry. A clean 25-session path after t0 is required
so every possible day-5 trigger has a comparable 20-session entry-anchored outcome.

## Frozen diagnostics

- Severe downside is Ret20 <= -10% or MAE20 <= -10%.
- Depth interaction is (-40%,-30%] versus <= -40%; it does not redefine the carrier.
- Broad periods are 2020, 2021-2023, and 2024-2026 because inherited signal evaluation starts
  in 2020.
- Liquidity uses coarse pooled thirds of the inherited 20-session median amount.
- PIT-industry checks are descriptive only.

Gross returns omit costs, slippage, market impact, and portfolio overlap. V2 is a timing
falsification, not a strategy backtest.
