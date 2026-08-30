# Five-day Market Intraday Non-slope Process Map

Frozen before MKT-MIN-PATH-001 construction. This outcome-blind map reuses the
exact required-scale MKT-MIN-001 daily/trajectory artifacts. It does not read or
rescan raw minute rows and does not promote an endpoint or three-day neighbor as
a replacement for any rejected five-day OLS slope.

## Fixed candidate manifestations

The map selects twelve descriptors before inspecting non-slope results. They
cover distinct economic questions without flattening all 34 minute descriptors
into a feature search.

| Candidate mechanism | Frozen descriptors | Question, not assumed truth |
|---|---|---|
| Selling pressure / recovery | `downside_excursion`, `down_minute_volume_share`, `longest_below_vwap_fraction`, `recovery_speed_30bar` | Is adverse excursion/time/volume progressively easing, or recovery progressively strengthening? |
| Demand / acceptance | `late_vwap_acceptance_fraction`, `close_location`, `positive_minute_fraction`, `new_intraday_high_fraction` | Is late acceptance, close strength, positive participation, or repeated-high behavior progressing? |
| Volatility contraction/expansion | `intraday_log_range`, `minute_realized_volatility`, `vwap_deviation_std` | Is realized range/oscillation contracting, expanding, reversing, or curving? |
| Volume-path structure | `minute_volume_concentration` | Is intraday volume concentration progressing or changing shape? |

Passing a representation does not prove supply exhaustion, demand strengthening,
compression usefulness, accumulation, or distribution. Those labels require
later falsification against distinct manifestations and eventually outcomes.

## Three fixed non-slope operators

For values `v1..v5` from Day -5 through Day -1 and adjacent changes
`d1..d4`:

### A. Ordinal progression

- Primary: `mean(sign(d1..d4))`, the balance of rising versus falling adjacent
  steps.
- Neighbor 1: mean sign across all ten ordered day pairs.
- Neighbor 2: rank correlation between day order 1..5 and the five values.

This is an order/count representation. It does not use OLS magnitude or endpoint
change. Zero changes remain zero.

### B. Signed reversal

- Primary: when the mean of `d1,d2` and mean of `d3,d4` have opposite nonzero
  signs, emit the late sign; otherwise zero.
- Neighbor 1: the same signed reversal using only `d1` and `d4`.
- Neighbor 2: compare the direction from mean(`v1,v2`) to `v3` with the
  direction from `v3` to mean(`v4,v5`); emit the late sign only when opposite.

This is a discrete path topology. It does not imply a tradable reversal.

### C. Curvature / acceleration

- Primary: mean(`d3,d4`) minus mean(`d1,d2`).
- Neighbor 1: `d4 - d1`.
- Neighbor 2: `v5 - 2*v3 + v1`.

This tests change in adjacent pace, not the rejected OLS5 level slope. Positive
or negative orientation retains each descriptor's raw semantics.

## Aggregation, coordinates, and portability

Every operator is independently constructed on the daily cross-sectional
median, p40, and p60 descriptor series. The median is primary; p40/p60 are fixed
aggregation neighbors. All primary trajectories preserve absolute value,
strictly causal expanding/trailing-756 percentile and robust-z coordinates after
504 observations, same-date difference from ALL_A, and governed-view rank.

The exact views remain ALL_A/SH_A/SZ_A/CHINEXT_BOARD and the exact denominators
remain ALL_STATUS/NON_ST. The trajectory decision time is the fifth completed
close at 15:00 Asia/Shanghai; no later minute or date enters the five values.

## Frozen gates and compression

Each of the 36 descriptor/operator primaries separately requires raw coverage
at least 95%; median within-group Spearman at least 0.70 against both operator-
definition neighbors; median within-group Spearman at least 0.70 against both
p40/p60 aggregation versions; ALL_STATUS/NON_ST median Spearman at least 0.90;
nondegenerate view-year cells with at least 150 observations; and at least 95%
expected PIT/relative coverage.

Stable primaries with absolute Spearman at least 0.85 to the current Day -1
same-session level are retained as valid path descriptors but excluded from the
minimal trajectory panel as level-redundant. Remaining roles are compressed at
absolute Spearman 0.85 using the frozen descriptor order in this map and
operator order progression, reversal, curvature. Reversal roles must also have
both nonzero signs in every eligible view-year cell; a degenerate zero-dominated
cell fails rather than being reweighted.

No failed descriptor/operator may be replaced by a favorable definition,
aggregation, view, denominator, year, old endpoint/OLS field, or another member
of its candidate mechanism. Every attempted representation remains in the
ledger.

## Interpretation boundary

MKT-MIN-PATH-001 may freeze stable non-slope five-day trajectory descriptors.
It cannot by itself establish supply exhaustion, demand strengthening,
accumulation/distribution, support defense, breakout acceptance, forecastability,
habitat usefulness, entry timing, or a new strategy archetype.
