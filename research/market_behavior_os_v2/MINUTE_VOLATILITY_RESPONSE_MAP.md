# Continuous minute-volatility temporal-response map

Frozen before MKT-MIN-VOL-RESP-001 constructs any forward response.
MKT-MIN-PATH-002 and MKT-MIN-VOL-GEO-002 established a stable, externally
distinct continuous ordinal path. MKT-MIN-VOL-STATE-001 rejected exact discrete
states. This experiment does not rescue those states. It asks whether the
continuous path has a portable strategy-independent temporal relationship with
future market-wide minute volatility.

## Predictor and controls

The sole predictor is
`minute_realized_volatility__ordinal_progression`, available at 15:30 after the
completed current-session 15:00 minute bar.

The fixed current-state controls are:

1. log of current same-session minute realized-volatility median;
2. accepted 20-session daily realized-volatility level;
3. accepted smoothed daily intraday range;
4. accepted cross-sectional volatility concentration;
5. accepted five-session daily realized-volatility change.

No neighbor, failed path role, discrete state, market return, or strategy field
enters as a predictor.

## Future response and availability

From the frozen MKT-MIN-001 daily market panel, for each governed group compute

`log(minute_volatility_level[t+h] / minute_volatility_level[t])`

at h = 1, 3, and 5 later exchange sessions. The five-session response is the
primary because it matches the fixed path horizon; one and three sessions are
required neighboring temporal scales and cannot replace a failed primary.

The response at horizon h is not available until 15:30 on session t+h. It is an
outcome for this strategy-independent association study, never a predictor at
t, and creates no trade or same-bar fill.

## Frozen temporal validation

- Discovery block: predictor dates in 2019-01-01 through 2021-12-31.
- Untouched confirmation block: predictor dates in 2022-01-01 through
  2023-12-29, with the last h rows naturally absent when no future level exists.
- 2018 is excluded from effect estimation.

For each horizon/block/eight governed groups, report raw Spearman and partial
rank correlation after the five fixed controls. The partial rank correlation is
the primary evidence. No coefficient or sign is selected on confirmation.

Because three- and five-session responses overlap, also evaluate the primary
five-session response on a fixed phase-zero non-overlapping sample: within each
group/block, sort by predictor date and retain row positions 0, 5, 10, ... . No
phase search is permitted.

## Fixed evidence gates

1. At least 700 valid observations/group in discovery and 450/group in
   confirmation for every full-sample horizon; at least 120/80 per group in the
   discovery/confirmation non-overlapping five-session samples.
2. Primary five-session median absolute partial rho is at least 0.10 in both
   blocks; the block median signs are identical and nonzero.
3. At least six of eight group partial-rho signs agree with their block median
   in both blocks for the primary.
4. One- and three-session median absolute partial rho are each at least 0.05 in
   both blocks and share the primary sign in both blocks.
5. Fixed non-overlapping five-session median absolute partial rho is at least
   0.08 in both blocks, shares the primary sign, and has at least five of eight
   group signs agreeing in each block.

All gates must pass. No favorable horizon, block, group, denominator, view,
phase, control subset, sign, or raw rather than partial association may rescue a
failure.

## Claim boundary

Passing establishes only a replicating conditional association with subsequent
market minute-volatility change—positive sign for continuation, negative for
reversal. It does not establish causality, market-return prediction, strategy
usefulness, habitat fitness, entry/exit timing, or an executable volatility
strategy. Failure leaves the continuous coordinate as descriptive state only.
