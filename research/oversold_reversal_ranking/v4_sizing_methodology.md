# V4 Risk-Aware Sizing Methodology and Outcome-Blind Freeze

This document freezes V4 before any V4 weighted outcome is calculated. The carrier, event
cohort, outcome chronology, V3 features, component orientations, same-date normalization,
equal-weight score, and V3 quintile assignments are inherited without modification. V4
changes only event position weight.

## Frozen carrier, event, and score

- Carrier: exact V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%` at t0.
- Event: first carrier observation after no carrier observation in the prior 20 trading rows.
- Cohort: the exact 22,357-event V3 cohort after the already explained 186 zero-range t0
  exclusions. Legal next-open entry and clean V2/V3 outcome paths are unchanged.
- Features: close-location danger, current-day loss danger, five-session negative-day
  persistence, and adverse-gap danger, exactly as implemented in V3.
- Score: the equal average of the four same-date danger `percent_rank` components. Higher is
  more dangerous. V3 `risk_q` remains Q1 safest through Q5 riskiest.

The V3 score is causally available in an end-of-day batch. Its rank universe contains every
contemporaneous deep-carrier observation with complete t0 features, before event
de-duplication and before future-outcome availability filtering. All membership and inputs are
known by that date's close; no future cross-sectional membership, trigger, MAE, MFE, or return
enters the score. The pooled V3 Q1-Q5 boundaries are full-sample descriptive assignments,
however, so this V4 mapping is an event-level allocation falsification rather than a finished
deployable threshold policy.

## Frozen sizing policies

All events retain positive allocation. No veto is tested.

1. **Equal size:** Q1-Q5 weight `1.0`.
2. **Primary capital-preserving risk-aware size:** raw Q1-Q5 weights
   `1.25, 1.125, 1.00, 0.875, 0.75`. Divide every raw weight by its exact
   cohort-weighted mean. With frozen V3 counts `4,472, 4,472, 4,471, 4,471, 4,471`, the raw
   mean is `1.0000167732701168`, the normalizer is `0.999983227011221`, and final weights are
   approximately `1.24997903, 1.12498113, 0.99998323, 0.87498532, 0.74998742`. The exact
   cohort mean is 1.0.
3. **Secondary conservative overlay:** Q1-Q5 weights
   `1.00, 0.95, 0.90, 0.80, 0.70`, without normalization. Its expected frozen cohort mean is
   approximately `0.87000939`. Any lower risk is partly mechanical and cannot establish
   allocation skill.
4. **Simple constituent comparison:** apply the same normalized primary schedule to V3's
   frozen pooled `close_location_q`, higher close-location danger receiving less weight. This
   is descriptive and is the only constituent comparison.

No slope, alternative schedule, feature, or threshold will be tested after outcome inspection.

## Frozen capital arithmetic and diagnostics

For event weight `w`:

- weighted Ret5/10/20 = `w * Ret5/10/20`;
- capital MFE20 = `w * MFE20`; and
- capital MAE20 = `w * MAE20`.

The stock-path label `MAE20 <= -10%` remains the underlying severe-event label and cannot be
changed by sizing. The separate capital-severe label is frozen as
`capital_MAE20 <= -10%`, using the same loss threshold after applying event weight. Report
mean, median, 10th-percentile, and 25th-percentile capital MAE. Return/downside efficiency is
`mean weighted Ret20 / abs(mean capital MAE20)`; it is descriptive, not a Sharpe ratio.

Capital concentration for a future outcome group is `sum(weight in group) / sum(weight)`.
Capital retention for a group is its mean weight relative to the equal-size baseline weight
of 1.0. Future group labels never enter weight construction. The frozen large-winner label is
V3's existing immediate Ret20 `>= +10%`; positive and losing events use Ret20 `> 0` and
`<= 0` respectively.

Quintile return/downside contributions are `sum(weight*outcome in quintile) / full cohort N`,
so their sums reconcile to full-cohort mean weighted outcomes.

## Frozen stability analyses

- Broad periods: 2018-2020, 2021-2023, and 2024-2026. Inherited signal eligibility begins in
  2020, so the first block contains observed 2020 events only.
- Liquidity: the exact V2/V3 pooled liquidity thirds; the global sizing map is unchanged.
- PIT industry: summarize industries with at least 50 events; no industry-specific map.

## Interpretation boundary

V4 is an event-level allocation study. Overlapping opportunities, simultaneous capital
competition, daily NAV, transaction costs, impact, and portfolio constraints remain outside
scope. Equal mean event weight is the anti-triviality control; it is not proof that every date
has equal invested capital. A positive V4 result can justify one later portfolio experiment,
but V4 itself is not a portfolio backtest.
