# Same-session market intraday mechanism map

Frozen before MKT-MIN-SUPACC-001 construction. This study uses only the
required-scale MKT-MIN-001 daily market panel. It does not reopen 1.47 billion
raw minute rows, use future data, or reuse failed five-day path operators.

## Semantic boundary

The available descriptors support three narrower hypotheses:

1. `vwap_defense_recovery`: repeated recovery above session VWAP, limited dwell
   below VWAP, faster recovery from the intraday low, and shallow downside
   excursion.
2. `late_vwap_acceptance`: late time above session VWAP, session-wide time and
   volume above VWAP, and positive final-30-minute return.
3. `price_volume_demand_balance`: positive-minute participation, upside-minute
   volume, limited downside-minute volume, and upside excursion.

These are OHLCV-derived market-state hypotheses. They do not identify order
aggressors, participant intent, accumulation by named investors, or cross-day
support/resistance. MKT-MIN-001 explicitly lacks an action-safe cross-day minute
price level, so this study must not claim objective cross-day support tests.

## Fixed components and signs

| Mechanism | Positive-aligned components | Negative-aligned components |
|---|---|---|
| VWAP defense/recovery | VWAP recovery count; 30-bar-normalized recovery speed | longest fraction below VWAP; downside excursion |
| Late VWAP acceptance | late VWAP acceptance; time above VWAP; volume above VWAP; final-30-minute return | none |
| Price-volume demand balance | positive-minute fraction; upside-minute volume share; upside excursion | downside-minute volume share |

Every component is an accepted, internally minimal same-session level from
MKT-MIN-001. Rejected selloff duration, auction gap, redundant close/VWAP,
crossing, new-high, range, minute-volatility, and path fields are prohibited.

## Representation coordinates

The source's p40, median, and p60 absolute component values are preserved as
dimensionless cross-year-comparable vectors. They are not added in raw units.

For each component, view, denominator, and cross-sectional definition, build
the exact trailing-756-session causal percentile after 504 valid observations.
Positive components retain the percentile; negative components use one minus
the percentile. The primary mechanism score is the equal mean of the four
aligned component percentiles. Median and geometric mean are fixed aggregation-
shape neighbors.

The primary cross-sectional definition is the median. p40 and p60 are fixed
neighbors. Same-date relative-to-ALL_A is the primary mechanism score minus its
ALL_A value; governed-view percentile rank is computed from the mechanism score
across all four views. No optimized weight, PCA sign, threshold, or favorable
component subset is allowed.

## Stability and latent-mechanism gates

Each mechanism independently requires:

- all four source roles remain accepted and raw coverage after the inherited
  session gates is at least 95%;
- primary mean versus median/geometric aggregation has worst median within-
  group Spearman at least 0.70;
- primary mean versus each four possible leave-one-component-out mean has worst
  median within-group Spearman at least 0.70;
- median-definition primary versus p40 and p60 primary has worst median within-
  group Spearman at least 0.70;
- ALL_STATUS versus NON_ST median Spearman at least 0.90;
- every eligible 2021-2023 view/denominator/year score cell has at least 150
  observations and is nondegenerate;
- expected PIT and relative coverage, two byte-identical executions, and no
  fail-closed source violation.

Passing establishes a coherent representation vector/score, not a causal
mechanism. A failed exact score does not reject the broader defense, acceptance,
or accumulation/distribution family.

## Redundancy and daily-return control

After stability, compare each mechanism in causal-PIT and relative-rank space
with accepted current controls: open-to-close return, downside realized
volatility, and minute-volume concentration. Pairwise median absolute Spearman
must remain below 0.85. Fixed-control rank-OLS reconstruction must remain below
0.70 median and 0.85 maximum adjusted R2.

Mechanism scores are then compressed at a 0.85 pairwise edge in the fixed order
VWAP defense/recovery, late VWAP acceptance, price-volume demand balance.
Stable but redundant scores remain evidence about a shared latent manifestation
and are not counted twice. No control may be removed to promote a mechanism.

## PIT and claim boundary

All descriptors use completed 15:00 minute bars but the required-scale derived
artifact is available only at 15:30 Asia/Shanghai. No 15:00 or same-bar action
is allowed. Passing establishes same-session representation quality and
compression only. It does not establish future return, future volatility,
strategy usefulness, habitat fitness, entry timing, execution, or a new
archetype. Future values, strategy outcomes, failed path roles, raw minute rows,
post-2023 data, and CY-011 are prohibited.

## MKT-MIN-SUPACC-001 result

All three frozen scores pass the internal representation gates. The worst
median aggregation-shape, leave-one-out, and cross-sectional-definition
correlations are 0.892, 0.894, and 0.965 respectively; denominator stability is
at least 0.998.

Only `vwap_defense_recovery` survives external compression. Its maximum
pairwise PIT correlation is 0.764 and fixed-control joint reconstruction is
0.588 median/0.607 maximum adjusted R2 in PIT space. Late acceptance fails PIT
joint distinctness at 0.701 median adjusted R2. Demand balance is return-
redundant: PIT rho 0.914 with open-to-close return and PIT joint reconstruction
0.916 median adjusted R2. The two excluded composites remain stable descriptive
manifestations, not independent engine dimensions.

Two executions are byte-identical: panel `b08abaab...`, result `b09808a9...`,
report `e070f9a9...`. This result remains representation-only and preserves the
15:30 availability and all claim prohibitions above.
