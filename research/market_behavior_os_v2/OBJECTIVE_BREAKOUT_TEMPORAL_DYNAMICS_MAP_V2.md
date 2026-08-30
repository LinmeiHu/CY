# Objective prior-high repeated-event temporal dynamics map V2

Frozen after MKT-BREAKOUT-DYN-001 stopped before its first trajectory estimate.

## Exact semantic correction

The parent map and 001 spec incorrectly declared `market_sequence_rank` as the
within-block time coordinate. The first attempted sequence proved that field is
the deterministic symbol-selection ordinal encoded in `sequence_id`; it is
constant across the selected symbol's five dates. The first differing identity
was `2018|01|ALL_A|02|600576.SH / L10_CONTINUOUS`, with crossings on
2018-03-12 and 2018-03-13 both carrying selection rank 2.

The correct time coordinate is the already frozen `relative_day`, which is the
market-session position `-5,-4,-3,-2,-1` inside each selected five-session
block. A temporal endpoint rate therefore divides by
`last_relative_day - first_relative_day`. These are actual market-session gaps;
non-crossing days remain absent and are not compressed into event order.

## Exact inheritance

MKT-BREAKOUT-DYN-002 inherits the 001 scientific spec SHA-256
`09f29ecff92864cae4242bdad64632314298d690f5b09644f606d6b605df69eb`:

- the same seven roles and three prohibited roles;
- the same immutable source panel/result/spec/map/data hashes;
- the same L20 primary, L10/L40, and auction definitions;
- the same endpoint, OLS, and Theil--Sen operators;
- the same support, stability, geometry, direction, compression, scalar, and
  resource gates;
- the same deterministic bootstrap and scalar-selection seed identity, so the
  control correction does not introduce a second randomization;
- the same PIT-B, 15:30 availability, no-outcome, no-strategy, no-post-2023,
  and no-CY-011 boundaries.

Only the declared time coordinate and output experiment identity change.
`market_sequence_rank` remains an audited selection attribute and is prohibited
as a temporal denominator. No role-specific count, sign, correlation, or result
from the invalid 001 attempt exists or informed this correction.
