# Objective support data contract V3

Frozen before MKT-SUPPORT-DATA-003 accesses QD-004. This is the source-role
correction selected by SYNTH-MKT-030. It inherits MKT-SUPPORT-DATA-002's exact
eligible-sequence sample, action challenge, causal history, population, minute,
lineage, limit, and claim contracts by immutable spec/runner hashes.

## Invalid parent boundary

MKT-SUPPORT-DATA-002 incorrectly required QD-004's final minute close to equal
CY-006's official daily close. The first binary mismatch was
8.520000457763672 versus 8.52. A complete frozen-target diagnostic found 1,161
bitwise and 39 integer-cent mismatches among 1,225 unique sessions. CY-008 does
not promise this equality. No 002 output is accepted.

003 does not add a numerical tolerance and does not resample. It corrects the
source roles.

## Exact shared-coordinate construction

For a target date t:

- CY-006 supplies raw daily close `D_t` and the causal continuous close `C_t`.
- The positive finite coordinate scale is exactly `S_t = C_t / D_t` in the
  runtime's binary double arithmetic.
- QD-004 supplies every observed raw minute OHLC value `P_t,m`.
- The mapped minute coordinate is exactly `P*_t,m = P_t,m * S_t`.

This is algebraically the same causal action coordinate used for prior daily
lows. No daily value replaces a minute value. In particular, mapped QD-004 final
close is not forced to equal `C_t` when the independent QD-004 final bar differs
from `D_t`.

Require positive finite `D_t`, `C_t`, `S_t`, every raw minute OHLC, and every
mapped minute OHLC. The output must retain raw daily close, raw minute final
close, scale, mapped final close, binary equality, raw signed/absolute close
difference, and a deterministic positive-price integer-cent diagnostic defined
as `floor(price * 100 + 0.5)`. The cent diagnostic is descriptive only and may
not gate, round, or alter any transformed price.

## Inherited gates

- exact frozen file/spec/runner identities and full content hashes;
- six fixed five-session date blocks, four views, ten complete CY-006 sequences
  per year/view, and exact hash ordering;
- five independent supported action sessions per year;
- complete 40-step action coordinate, no rights/blocking/unresolved actions;
- strictly prior 10/20/40-session objective daily-low candidates;
- exactly 241 raw bars, exact auction/continuous/lunch/close grid, raw adjust
  `none`, units, internal OHLC, volume/amount reconciliation, CY-008 snapshot
  binding, positive finite limit prices, and 15:30 availability;
- every full daily population cell above its unchanged floor;
- no within-003 replacement, imputation, chain repair, future adjustment,
  tolerance, favorable-source selection, or minute-aware sample selection.

## Claim boundary

Passing establishes only bounded PIT-B source-role and coordinate feasibility.
It establishes no support, resistance, defense, recovery, accumulation,
distribution, prediction, habitat, timing, execution, or strategy. Future
values, strategy/outcome fields, post-2023 data, and CY-011 remain prohibited.
