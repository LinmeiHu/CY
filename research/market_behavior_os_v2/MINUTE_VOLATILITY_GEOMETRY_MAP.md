# Minute-volatility path geometry map

Frozen before MKT-MIN-VOL-GEO-001 construction. This map asks whether the only
accepted five-day non-slope minute path is a distinct market-state coordinate or
another manifestation of already-frozen volatility states. It does not test
future returns, strategy usefulness, habitats, triggers, or actions.

## Fixed roles

The target is only
`minute_realized_volatility__ordinal_progression` from MKT-MIN-PATH-002. It is
the mean sign of four adjacent Day -5..Day -1 changes in the market
cross-sectional median of per-security minute realized volatility. Its stable
all-pair and rank-time definitions remain representation evidence; they are not
new geometry candidates.

The five controls are fixed before construction:

| Control | Frozen source | Semantic role |
|---|---|---|
| Day -1 minute realized-volatility level | MKT-MIN-PATH-002 | Same-session level underlying the path |
| 20-session realized volatility | MKT-VOL-001 | Daily close-to-close volatility level |
| 5-session smoothed intraday range | MKT-VOL-001 | Daily-bar intraday amplitude |
| Top-decile volatility mass share | MKT-VOL-001 | Cross-sectional volatility concentration |
| 5-session realized-volatility change | MKT-VOL-001 | Daily-bar volatility transition |

No failed MKT-MIN-PATH-002 role or rejected MKT-VOL-001 term-structure,
asymmetry, downside, or dispersion candidate may enter.

## Common observation and availability

Join exactly on trade date, governed market view, and denominator. Every frozen
MKT-VOL-001 row from 2018-07-03 through 2023-12-29 must match exactly one hard-
valid MKT-MIN-PATH-002 row. The daily controls are available at 15:00 and the
five-day minute path after the completed 15:00 minute bar at 15:30
Asia/Shanghai. The geometry decision timestamp is therefore 15:30. It creates
no action; any later use must execute after that timestamp under a separate
contract.

## Three geometry views

1. Absolute: within each of eight view/denominator histories, Spearman
   association of the raw path with each raw control.
2. Strict PIT: the same associations using only causal expanding-percentile
   coordinates supplied by the frozen panels.
3. Relative: for each denominator, association of path versus control using
   both view-minus-ALL_A and governed-view-rank coordinates.

The same-session minute level has only an accepted absolute coordinate and is
tested only in the absolute and joint-raw views. No PIT or relative level is
reconstructed after the fact. The four daily controls have all three frozen
coordinate families.

For each control, report every group result, median absolute association, and
maximum absolute association. The primary external-redundancy boundary is 0.85:
the path is pairwise distinct from a control only when the median absolute
association is below 0.85 in every available view. Maximum associations remain
visible and cannot be removed by excluding a view or denominator.

As a multivariate diagnostic, regress within-group average ranks of the path on
the five control ranks with an intercept. Report adjusted R-squared for every
group. The path passes joint nonreconstruction only when median adjusted
R-squared is below 0.70 and the maximum is below 0.85. No coefficient is a
forecast or economic effect.

## Gates and claim boundary

- immutable panel and result hashes must match;
- input columns are allowlisted and outcome/strategy/CY-011 fields prohibited;
- keys must be unique, the common population exact, availability causal, and
  all eight groups present;
- all 2019-2023 group/year cells must contain at least 150 nonmissing,
  nondegenerate observations for target and controls;
- no view, denominator, coordinate, or favorable control can rescue a failed
  redundancy gate;
- byte-identical reruns are required.

Passing establishes only a distinct contemporaneous volatility-path
coordinate. Failing compresses it into the frozen volatility mechanism family.
Neither outcome establishes contraction/expansion, prediction, causality,
habitat fitness, or a strategy rule.
