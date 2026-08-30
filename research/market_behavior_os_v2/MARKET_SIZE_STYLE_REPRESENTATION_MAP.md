# Strategy-independent circulating-size representation map

Frozen before MKT-STYLE-001 constructs size buckets or role values. The map is
limited to circulating-market-value size under the passing MKT-STYLE-DATA-001
contract. It does not represent total market cap, true free float, growth/value,
beta, profitability, investment, fund flow, or participant identity.

## Assignment and return semantics

For each market view and denominator, calculate each security's completed-close
circulating value at t-1 as raw close times causal circulating shares. Assign
same-session t returns to size buckets using the t-1 value and only when t-1 and
t are consecutive exchange sessions with valid causal coordinates. Current t
close must never determine the bucket used to attribute the t return.

Security t return uses the existing causal corporate-action bridge: ordinary
raw close-to-close when no action exists; on a visible supported action day,
prior close is transformed by the declared cash/share multiplier; rights or
blocking/unknown actions fail closed. No future-adjusted price enters.

Primary small/large tails are bottom/top 30% of the within-view/denominator t-1
size rank. Bottom/top 20% and 40% are fixed neighbors. Three equal size buckets
support diffusion/concentration; five equal buckets support curve divergence.
Every extreme bucket requires at least 50 securities and every quintile at least
30. No absolute CNY bucket boundary or present-day membership is allowed.

## Representation roles

| Role | Primary | Fixed neighbors | Economic distinction |
|---|---|---|---|
| Size structure | IQR of log circulating value | p90-p10; median absolute deviation | Cross-sectional size breadth, not return leadership |
| Positive participation balance | positive-return fraction small30 minus large30 | small20-large20; small40-large40 | Breadth of advancing names by size |
| One-day size leadership | equal-weight t return small30 minus large30 | 20/80; 40/60 tails | Immediate signed endpoint leadership |
| Twenty-day size leadership | 20-session cumulative log small30-minus-large30 daily portfolio spread | 10 and 40 sessions | Persistent leadership scale |
| Winner diffusion | normalized entropy of top-10% t return winners across three size buckets | top 5%; top 20% | Whether winners span size groups |
| Positive-mass concentration | largest share of positive t return mass across three size buckets | HHI; one-minus normalized entropy | Whether positive performance is size-concentrated |
| Size-curve divergence | standard deviation of five size-quintile equal-weight t returns | max-min range; mean adjacent gap | Non-endpoint separation across the size curve |
| Leadership transition | 20-session leadership minus its value five sessions earlier | three; ten sessions | Continuous change in established size leadership |

These are falsifiable representations. “Small-cap effect,” “risk appetite,” and
“style rotation” are not assumed interpretations.

## Absolute, causal-PIT, and relative coordinates

Preserve each primary and its neighbors in absolute units: log-CNY dispersion,
dimensionless participation/concentration/diffusion, and return/log-return
spreads. For each primary within view/denominator, construct exact trailing-756-
session causal percentile and robust-z coordinates after 504 valid observations,
including the current observation.

For each primary also preserve same-date/denominator relative-to-ALL_A and
governed-view percentile rank. These coordinates support cross-year comparison
without replacing absolute values. No global full-sample normalization, PCA,
optimized weights, or threshold search is permitted.

## Representation gates

Each role independently requires:

- at least 95% raw coverage after inherited row/bucket gates in every view;
- median primary-versus-each-neighbor Spearman at least 0.70 across views;
- ALL_STATUS versus NON_ST median Spearman at least 0.90;
- at least 150 nondegenerate observations in every eligible 2019--2023
  view/year cell;
- expected causal-PIT and relative-coordinate coverage;
- exact 15:00 availability, source/PIT/lineage preservation, and two byte-
  identical executions.

Passing roles are compressed at absolute Spearman 0.85 on ALL_A/ALL_STATUS in
this fixed priority: size structure, positive participation balance, one-day
leadership, twenty-day leadership, winner diffusion, positive-mass
concentration, size-curve divergence, leadership transition. A redundant role
remains a manifestation and is not counted as independent evidence.

## Claim boundary

Passing establishes stable, portable, nonredundant circulating-size state
representations only. It does not establish future return, a small-cap premium,
risk appetite, style timing, strategy habitat, entry/exit, execution, capacity,
causality, or a new archetype. Future values, strategy outcomes, post-2023 data,
unregistered style fields, and CY-011 are prohibited.

## MKT-STYLE-001 result

Six roles survive construction and fixed-priority compression: size structure,
positive participation balance, winner diffusion, positive-mass concentration,
size-curve divergence, and leadership transition. Their worst neighboring-
definition rho is 0.723--0.988 and denominator rho 0.973--0.997; all causal-PIT,
robust-z, and relative expected coverage is 1.000.

One-day return spread is stable but redundant with positive participation
balance at rho 0.903. Twenty-day leadership fails the fixed 10/20/40 family:
neighbor rho is 0.683 for 10 days and 0.634 for 40 days. Neither can be rescued
by choosing a favorable horizon or counting a redundant role twice.

Two valid single-thread executions are byte-identical: panel `5ed52618...`,
result `134dc205...`, report `4da04ee0...`. This remains representation-only.
