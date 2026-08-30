# MKT-RISK-001 directional-tail and risk-appetite representation

## Construction boundary

- Status: `COMPLETE_STRATEGY_INDEPENDENT_DIRECTIONAL_TAIL_REPRESENTATION`
- Source: 6,155,390 CY-006 rows, 2018-01-02..2023-12-29.
- Causal core: 5,036,345 security-dates; exact valid limit coordinate on 0.999880.
- Coordinate support: [-1.000000, 1.000000].
- Group/dates invalidated below the unchanged 99% limit-coordinate gate: 1.
- Strategy fields, future returns, MKT-SHOCK-001 score, and CY-011 read: **none**.
- Representation stability is not panic, forecast, habitat, or strategy usefulness.

## Frozen representation gates

| Role | Min coverage | Worst neighbor rho | ST rho | PIT | Relative | Gate | Novel minimal panel |
|---|---:|---:|---:|---:|---:|---|---|
| central_direction | 1.000 | 0.995 | 1.000 | 1.000 | 1.000 | PASS | ACCEPT |
| upside_participation | 1.000 | 0.963 | 1.000 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| downside_participation | 1.000 | 0.967 | 1.000 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| upside_tail_depth | 1.000 | 0.969 | 0.998 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| downside_tail_depth | 1.000 | 0.982 | 0.999 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| upside_extreme_participation | 1.000 | 0.965 | 0.987 | 1.000 | 1.000 | PASS | ACCEPT |
| downside_extreme_participation | 1.000 | 0.940 | 0.955 | 1.000 | 1.000 | PASS | ACCEPT |
| upside_leadership_concentration | 1.000 | 0.997 | 1.000 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| downside_pressure_concentration | 1.000 | 0.997 | 0.999 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| directional_industry_diffusion | 1.000 | 0.987 | 0.999 | 1.000 | 1.000 | PASS | internally_redundant_with:central_direction |
| tail_risk_appetite_balance | 1.000 | 0.952 | 0.985 | 1.000 | 1.000 | PASS | deterministic_composite_of:upside_extreme_participation,downside_extreme_participation |

## Outcome-blind compression

- Absolute-Spearman 0.85 components: `[['central_direction', 'upside_participation', 'downside_participation', 'upside_tail_depth', 'downside_tail_depth', 'upside_extreme_participation', 'upside_leadership_concentration', 'downside_pressure_concentration', 'directional_industry_diffusion', 'tail_risk_appetite_balance'], ['downside_extreme_participation']]`.
- Novel minimal roles: `central_direction, upside_extreme_participation, downside_extreme_participation`.
- Upside/downside counterparts remain separately diagnosed; high negative correlation alone does not merge their semantics.
- External controls are frozen discovery/leadership and accepted volatility roles only. External redundancy is descriptive and outcome-blind.

| Role | Largest external median absolute rho | Control |
|---|---:|---|
| central_direction | 0.427 | `breadth_net_new_high_low60` |
| upside_participation | 0.449 | `breadth_net_new_high_low60` |
| downside_participation | 0.439 | `breadth_net_new_high_low60` |
| upside_tail_depth | 0.581 | `breadth_net_new_high_low60` |
| downside_tail_depth | 0.428 | `volatility_mass_share_top10` |
| upside_extreme_participation | 0.645 | `breadth_net_new_high_low60` |
| downside_extreme_participation | 0.374 | `volatility_mass_share_top10` |
| upside_leadership_concentration | 0.425 | `breadth_net_new_high_low60` |
| downside_pressure_concentration | 0.393 | `breadth_net_new_high_low60` |
| directional_industry_diffusion | 0.446 | `breadth_net_new_high_low60` |
| tail_risk_appetite_balance | 0.664 | `breadth_net_new_high_low60` |

## Reproducibility

- Spec SHA-256: `7b5303c38b278b042a7d0fabea653e7c78c3f5e781cfcaf5847a36a28c2764a8`
- CY-006 manifest SHA-256: `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`
- Panel SHA-256: `fe7436e26d616455c7ce897eb70d53749e9185285082453549d338afe53009b1`
