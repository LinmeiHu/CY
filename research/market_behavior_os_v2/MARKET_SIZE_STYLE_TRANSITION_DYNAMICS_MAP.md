# Circulating-size leadership-transition dynamics map

Frozen before MKT-STYLE-DYN-001 shifts any future state. The study asks only
whether the externally distinct circulating-size leadership-transition
coordinate has a repeatable nonoverlapping state dynamic. It does not test
future market payoff or a size-timing strategy.

## Primary process

Let `L20(t)` be the already-constructed twenty-session cumulative small30-minus-
large30 log-return spread. The accepted transition representation is

`T5(t) = L20(t) - L20(t-5)`.

The primary response is the same accepted representation five sessions later:

`T5(t+5) = L20(t+5) - L20(t)`.

The daily size-return components in `T5(t)` and `T5(t+5)` do not overlap. The
current transition uses the newest and dropped five-session blocks at t; the
response uses the next and then-dropped five-session blocks. Passing positive
association would be labeled state persistence; passing negative association
would be labeled state reversal. The sign is learned once from reused block A
and must reproduce everywhere else.

This use of `T5` does not revive the rejected 10/20/40 leadership-level family.
The transition role independently passed its 3/5/10 definition-stability gate.

## Fixed neighboring definitions

Repeat the same nonoverlapping construction for the accepted transition
neighbors:

- `T3(t)` versus `T3(t+3)`;
- `T10(t)` versus `T10(t+10)`.

Both must support the primary learned sign in both reused temporal blocks. They
are robustness challenges, not alternative horizons, and cannot rescue a
failed five-session primary.

## Current-state controls

Partial-rank estimation uses exactly three t controls:

- accepted size positive-participation balance;
- accepted size-curve divergence;
- accepted broad realized-volatility change.

They separate transition recurrence from current size breadth, cross-size return
amplitude, and broad volatility transition. No control may be deleted. Failed
size leadership levels, size structure, one-day leadership, and other rejected
or compressed roles are prohibited.

## Coordinates and temporal blocks

The primary uses raw, causal three-year PIT percentile, relative-to-ALL_A, and
governed-view rank coordinates. Relative rank uses the corrected same-date
four-view unit with date fixed effects. The raw 3/10 neighbors are definition
challenges only because their own PIT/relative coordinates were never frozen.

Both blocks are already-consumed exploratory time:

- reused block A: 2021-01-01 through 2021-12-31;
- reused block B: 2022-01-01 through 2023-12-31.

Predictor and response availability dates must both lie in the same block. A
phase-zero sample takes every fifth valid predictor in each group and block so
primary response intervals do not overlap across observations.

## Frozen gates

Before estimation require at least 150 complete observations per ordinary
group/block, 600 pooled four-view observations per rank denominator/block, and
40 observations per phase-zero group/block.

The five-session primary requires:

- raw median absolute partial Spearman at least 0.10 in both blocks;
- the learned sign in at least six of eight raw groups per block;
- block-B absolute magnitude at least half block A;
- phase-zero raw median absolute partial Spearman at least 0.08 and sign support
  in six of eight groups per block;
- PIT median absolute partial Spearman at least 0.08 and sign support in six of
  eight groups per block;
- relative-to-ALL_A median absolute partial Spearman at least 0.05 and learned-
  sign support in five of six groups per block;
- corrected relative-rank absolute partial association at least 0.05 and the
  learned sign in both denominators per block.

Each raw three/ten-session neighbor requires median absolute partial Spearman at
least 0.06 and learned-sign support in six of eight groups in both blocks. All
gates are conjunctive. No sign, horizon, block, coordinate, phase, view,
denominator, control deletion, failed role, or favorable subset can rescue a
failure.

## Claim boundary

Passing establishes only a recurring outcome-blind circulating-size transition
state process. It does not establish a small-cap premium, future market return,
stock selection, risk appetite, habitat fitness, timing, execution, capacity,
causality, or a strategy rule. Post-2023 data, strategy outcomes, and CY-011 are
prohibited.
