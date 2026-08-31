# Formation-depth tail-risk mechanism attribution map

Frozen after MKT-BREAKOUT-ECON-001 and HAB-CHX-FORMDEPTH-001, before any new
residual response estimate. The question is whether the supported formation-depth
downside state is incremental objective-formation information or a manifestation
of generic same-day market direction/return/range geometry.

## Fixed target and response

- Target state: the exact seven-role parent field
  `breakout_formation_depth20` and its causal `pit_3y_pct`.
- Response: only the already-frozen equal-weight mean constituent adverse log
  excursion at h=3.
- Neighbor challenges: the same h=1 and h=5 downside responses.
- No terminal-return, transition, strategy, or alternate objective-crossing role
  is reopened.

## Mandatory alternatives

Every complete cell uses the original discovery-breadth and realized-volatility
PIT controls plus all three contemporaneous alternatives:

1. accepted central direction: `median_signed_limit_utilization`;
2. ordinary market open-to-close return: `open_close_log_return__median`;
3. ordinary market intraday range: `intraday_log_range__median`.

The minute-derived alternatives are available at 15:30 after the completed daily
session, so the joint attribution clock is 15:30. The future response still begins
at t+1. This later clock is valid for explanation only and cannot be backdated into
an entry predictor.

## Geometry and residual response

First report same-cell absolute/PIT Spearman between formation depth and every
alternative. Rank-regress formation depth on all five controls and report adjusted
R2 by cell and block. Pairwise absolute rho >=0.85 or median joint adjusted R2
>0.70 means the state is not a distinct direct coordinate under this attribution.

Then rank-residualize formation depth and downside response on the same five fixed
controls. The primary statistic is their residual correlation. In raw response
units, also regress downside on ranked controls and compare mean residual downside
at formation-depth PIT >=0.80 versus <=0.20.

`INCREMENTAL_OBJECTIVE_FORMATION_TAIL_RISK` requires:

- median h=3 partial rho magnitude >=0.10 and the original negative sign;
- at least six of eight cells share that sign;
- both fixed blocks share it with magnitude >=0.05;
- all four PIT-supported years and every supported-year leave-one-out share it;
- h=1 and h=5 medians do not reverse;
- at least two of three h=3 and four of five h=5 nonoverlap phases share it;
- median controlled PIT-tail residual gap is <=-0.0025;
- pairwise and joint directness boundaries pass.

If residual response fails, classify the MKT-BREAKOUT-ECON-001 result as
`GENERIC_SAME_DAY_RISK_MANIFESTATION_UNDER_EXTENDED_CONTROLS` without rewriting
its valid narrower fixed-control conclusion. If response survives but directness
fails, classify `ECONOMIC_RESPONSE_NOT_DISTINCT_COORDINATE`. No threshold,
control deletion, alternate minute descriptor, outcome, or strategy transfer may
rescue a failure.

Passing still establishes association, not causality or a strategy. Failing does
not invalidate formation depth as a stable descriptive level; it narrows its
economic interpretation. CY-011, post-2023 data, and strategy outcomes remain
prohibited.
