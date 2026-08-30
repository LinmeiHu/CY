# Objective support data contract V2

Frozen before MKT-SUPPORT-DATA-002 accesses any new QD-004 row. This is a
sample-estimand correction to invalid MKT-SUPPORT-DATA-001, not a relaxation of
its causal coordinate, history, minute, lineage, population, or claim gates.

## Invalid parent boundary

MKT-SUPPORT-DATA-001 reused 1,200 sessions selected for an earlier minute-
readiness question. Thirty-seven sessions fail its complete 40-step objective-
level coordinate: 17 are recent listings and 20 cross invalid or blocking
action history. Its no-replacement gate stopped before minute access. No 001
output is evidence.

MKT-SUPPORT-DATA-002 never replaces a failed 001 row. It defines a new sample
from the daily coordinate before QD-004 behavior is available to the selection
operator.

## Frozen market sequence sample

The six date blocks remain the exact five completed sessions used by the prior
readiness cohort:

| Year | Fixed sessions |
|---|---|
| 2018 | 06-08, 06-11, 06-12, 06-13, 06-14 |
| 2019 | 06-10, 06-11, 06-12, 06-13, 06-14 |
| 2020 | 06-08, 06-09, 06-10, 06-11, 06-12 |
| 2021 | 06-07, 06-08, 06-09, 06-10, 06-11 |
| 2022 | 06-08, 06-09, 06-10, 06-13, 06-14 |
| 2023 | 06-08, 06-09, 06-12, 06-13, 06-14 |

For each year and each governed view `ALL_A`, `SH_A`, `SZ_A`, and
`CHINEXT_BOARD`, a candidate symbol must be `coordinate_eligible` on all five
fixed dates. Exactly ten symbol sequences are selected by ascending
`SHA256(MKT-SUPPORT-DATA-002|MARKET|year|market_view|symbol)`. This produces
10 symbols x 5 dates x 4 views x 6 years = 1,200 cohort rows.

Selection reads only CY-006 daily/action fields and the frozen dates/view rules.
It may not inspect QD-004/CY-008 completeness, support tests, penetration,
recovery, volume, outcomes, or strategy membership. Cross-view duplicate
security-dates preserve separate cohort identities and share one raw audit.

## Independent action challenge

Retain five supported, non-rights, nonblocking, available action sessions in
each year, selected from coordinate-eligible CY-006 rows on or after March 1 by
ascending `SHA256(MKT-SUPPORT-DATA-002|ACTION|year|symbol|trade_date)`. The
action sample adds 30 rows and may not use minute behavior.

## Unchanged coordinate and minute contract

- Prior levels are the minimum causal action-coordinate daily low over exactly
  10, 20, and 40 completed sessions through t-1.
- Every required history row and bridge must be valid; no chain repair, fill,
  normalization, tolerance, or sample substitution is allowed.
- No-action bridge is prior raw close. A supported cash/share action bridge is
  `(previous_close-cash_per_share)/share_multiplier`; rights, blocking,
  unresolved, late, nonpositive, or invalid actions fail closed.
- Current raw QD-004 OHLC is mapped by `coordinate_close(t)/raw_close(t)` only
  after exact CY-006/QD-004 close equality.
- Require exactly 241 bars on the frozen auction/continuous/lunch/close grid,
  matching CY-008 lineage, exact units/reconciliation, positive finite limit
  prices, and completed-session availability at 15:30 Asia/Shanghai.
- All eight view/denominator population cells must pass the unchanged minimum
  on every eligible date.

## Claim boundary

Passing establishes only bounded PIT-B data and coordinate feasibility for a
later objective support/resistance representation map. It establishes no
support, defense, recovery, accumulation/distribution, prediction, habitat,
entry timing, execution, or strategy. Future values, outcomes, post-2023 data,
and CY-011 remain prohibited.
