# Directional-tail and Risk-appetite Representation Map

Frozen before MKT-RISK-001 construction. This map is strategy-independent and
outcome-blind. It supplies signed market state that the direction-neutral
MKT-SHOCK-001 score cannot supply. It does not presume panic, capitulation,
speculation, continuation, reversal, forecastability, or strategy usefulness.

## Representation unit

Each valid security contributes the signed limit-utilization coordinate `u`
defined in `RISK_APPETITE_DATA_CONTRACT.md`. Positive and negative sides remain
separate even when they are strongly contemporaneously related. A negative
correlation between the two sides is not evidence that the economic tails are
interchangeable.

## Representation map

| Concept | Economic question | Primary | Fixed neighbors | Claim boundary |
|---|---|---|---|---|
| Central direction | Where is the typical security within its applicable daily limit range? | cross-sectional median `u` | q40 and q60 of `u` | same-session direction, not trend |
| Upside participation | How broadly are securities advancing? | fraction `u > 0` | fractions `u > 0.05` and `u > 0.10` | participation, not tail demand |
| Downside participation | How broadly are securities declining? | fraction `u < 0` | fractions `u < -0.05` and `u < -0.10` | participation, not selling cause |
| Upside tail depth | How far has the upper return tail advanced relative to applicable limits? | q90 of `u` | q80 and q95 | depth, not participation |
| Downside tail depth | How far has the lower return tail declined relative to applicable limits? | negative q10 of `u` | negative q20 and q05 | positive-valued severity, not loss forecast |
| Upside extreme participation | How much of the market is using most of its available upward range? | fraction `u >= 0.70` | thresholds 0.50 and 0.90 | limit-relative demand, not exact limit-up count |
| Downside extreme participation | How much is using most of its available downward range? | fraction `u <= -0.70` | thresholds -0.50 and -0.90 | limit-relative pressure, not forced selling |
| Upside leadership concentration | Is positive same-day move mass concentrated in a small upper tail? | share of positive `u` mass in top 10% | top 5% and top 20% | same-day leadership, distinct from 60-day discovery leadership |
| Downside pressure concentration | Is negative same-day move mass concentrated in a small lower tail? | share of negative `u` mass in worst 10% | worst 5% and worst 20% | concentration, not crash mechanism |
| Directional industry diffusion | Is positive direction spread across causal industries? | fraction of industries with median `u > 0` | fraction with mean `u > 0`; fraction with positive participation exceeding negative participation | equal-industry state, not sector rotation |
| Tail risk-appetite balance | Does upside extreme participation exceed downside extreme participation? | +0.70 fraction minus -0.70 fraction | corresponding 0.50 and 0.90 balances | signed asymmetry, not a tradable risk-on/off rule |

Thresholds and quantiles are economically broad, symmetric, and frozen. They
are robustness definitions, not a grid. No timestamp, horizon, percentile, or
limit-utilization threshold may be optimized after construction.

## Gates and compression

Each primary requires at least 95% raw coverage after daily view eligibility,
median within-view Spearman at least 0.70 against each fixed neighbor,
ALL_STATUS/NON_ST median Spearman at least 0.90, and nondegenerate support in
every eligible view-year cell with at least 150 dates. Industry diffusion must
also pass the frozen mapping/member/industry gates. Causal-PIT and relative
coordinates must have at least 95% expected coverage.

Accepted primaries are clustered at absolute Spearman 0.85. The outcome-blind
minimal panel gives priority to central direction, signed participation, signed
tail depth, signed extreme participation, signed concentration, industry
diffusion, and tail balance in that order. Upside and downside counterparts are
reported separately and cannot be collapsed into each other solely because of
a high negative correlation.

For each accepted role, redundancy against the six frozen external controls is
reported across all eight view/denominator groups. A role with median absolute
Spearman at least 0.85 against any control remains a valid representation but is
excluded from the novel minimal panel as externally redundant. No external
control is refit or relabeled.

## Interpretation boundary

MKT-RISK-001 can establish that signed participation, depth, concentration,
diffusion, or asymmetry have stable representations. It cannot establish a
panic episode, a future payoff, a market habitat, a risk-on/off trading rule, or
a new strategy archetype. Those require later preregistered process or
usefulness research after representation roles are frozen.
