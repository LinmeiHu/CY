# Objective support physical-level feasibility contract

Frozen before MKT-SUPPORT-LVL-DATA-001 inspects tested-day level identity. This
is the one bounded semantic falsifier selected by SYNTH-MKT-035. The rolling-
definition MKT-SUPPORT-DYN-001 null remains authoritative and cannot be rescued
by this audit.

## Question and unit

Among the immutable MKT-SUPPORT-DYN-001 five-session sequences, how many
repeated-tested and twice-recovered sequences use one exactly unchanged causal
prior-low coordinate on every tested day?

The sequence remains the cohort unit. No date, symbol, view, test, recovery,
level, or minute descriptor is reselected. MKT-SUPPORT-DYN-001 supplies the
already constructed tested/recovered states; MKT-SUPPORT-DYN-DATA-004 supplies
the already audited L10/L20/L40 coordinates.

## Exact level identity

- Parse the immutable 17-significant-digit coordinate artifact with pandas
  `float_precision="round_trip"`.
- Convert each positive finite level to its IEEE-754 binary64 bit pattern.
- `constant_test_level=True` only when every tested day in the sequence has the
  same bit pattern for that exact horizon.
- No cent rounding, decimal rounding, price tolerance, relative tolerance,
  split adjustment, modal-level selection, subset selection, or near-touch band
  is permitted.
- A sequence with levels A,A,B is not constant even if two tested days share A.
  A sequence with only one tested day is not a repeated-test sequence.

This establishes only whether the causal coordinate is numerically unchanged.
It does not establish that market participants recognized it, that orders rested
there, or that it caused a recovery.

## Frozen views

Count identity separately for:

1. primary L20 continuous path;
2. L10 continuous neighbor;
3. L40 continuous neighbor;
4. L20 auction-inclusive path neighbor.

For each view report:

- repeated-tested sequences;
- constant-level repeated-tested sequences;
- twice-recovered sequences;
- constant-level twice-recovered sequences;
- tested-day-count and unique-level-count distributions;
- counts by 2018--2020 / 2021--2023, year, and governed market view.

Primary L20 continuous counts must first reproduce 315 repeated-tested and 269
twice-recovered exactly. Any disagreement is a correctness failure.

## Frozen adequacy gates

Primary L20 continuous constant-level repeated tests require at least:

- 120 total;
- 50 in each fixed temporal block;
- 15 in every year.

Primary L20 continuous constant-level twice-recovered sequences require at
least:

- 100 total;
- 40 in each fixed temporal block;
- 15 in every year.

Each L10/L40 continuous neighbor requires at least 80/60 constant-level
repeated/twice-recovered sequences total, 30/20 in each fixed block, and 10/8 in
every year. The L20 auction neighbor must meet the primary L20 floors. All
neighbor floors must pass before a same-level temporal dynamics map may be
considered; no neighbor can rescue the primary.

These are count-only adequacy gates. No rate, slope, sign, correlation, risk
difference, transition, generic-control relation, or process direction may be
computed inside MKT-SUPPORT-LVL-DATA-001.

## Data, reproducibility, and claim boundary

- Read only the bound 004 coordinate/sample/count artifacts and the bound
  MKT-SUPPORT-DYN-001 session/result artifacts.
- Read no raw minute or daily partition. Expected raw rows read: zero.
- Preserve exact cohort identity, 1,920 sequences, 9,600 rows, and 9,575 unique
  physical sessions.
- Select five scalar audit sequences by smallest SHA-256 among constant-level
  primary repeated-test sequences and reproduce bit patterns/counts without
  calling the vectorized count implementation.
- Execute twice and require byte-identical outputs.
- No future return, outcome, strategy field, post-2023 data, or CY-011 may enter.

Passing means only that an unchanged-coordinate repeated-test temporal map has
adequate support on already consumed exploratory data. It does not establish
support, defense, strengthening, weakening, transition, prediction, payoff,
timing, habitat, execution, or a strategy. Failure deprioritizes this exact
temporal support branch without closing the broader support/resistance family.
