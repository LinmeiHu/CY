# MKT-CLQ-001 correlation/liquidity representation freeze

## Construction boundary

- Status: `COMPLETE_STRATEGY_INDEPENDENT_CORRELATION_LIQUIDITY_REPRESENTATION_FREEZE`
- Source: 6,155,390 CY-006 rows; eligible liquidity audit: 5,814,399 rows.
- Output: 10,696 daily view/denominator rows.
- Strategy membership, outcomes, trades, future returns, and CY-011 read: **none**.
- This is representation-quality evidence, not a panic, recovery, impairment, habitat, or strategy claim.
- Minimal nonredundant roles: `co_movement, directional_synchronization, liquidity_activity, turnover_level, liquidity_concentration`.

## Representation gates

| Concept | Primary | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Relative coverage | Gate | Minimal panel |
|---|---|---:|---:|---:|---:|---:|---|---|
| co_movement | `correlation_median20` | 1.000 | 0.839 | 1.000 | 1.000 | 1.000 | PASS | ACCEPT |
| directional_synchronization | `directional_sync_balance5` | 1.000 | 0.753 | 0.998 | 1.000 | 1.000 | PASS | ACCEPT |
| liquidity_activity | `liquidity_median_amount_ratio20` | 1.000 | 0.738 | 1.000 | 1.000 | 1.000 | PASS | ACCEPT |
| liquidity_participation | `liquidity_fraction_amount_ratio20_above1` | 1.000 | 0.740 | 1.000 | 1.000 | 1.000 | PASS | redundant_with:liquidity_activity |
| turnover_level | `liquidity_turnover_median` | 1.000 | 0.993 | 0.999 | 1.000 | 1.000 | PASS | ACCEPT |
| liquidity_concentration | `liquidity_amount_share_top10` | 1.000 | 0.981 | 0.998 | 1.000 | 1.000 | PASS | ACCEPT |
| industry_liquidity_diffusion | `industry_liquidity_diffusion20` | 1.000 | 0.726 | 0.998 | 1.000 | 1.000 | PASS | redundant_with:liquidity_activity |
| liquidity_change | `liquidity_activity_change5` | 1.000 | 0.534 | 1.000 | 1.000 | 1.000 | FAIL | construction_gate_failed |

## Outcome-blind latent components

Absolute-Spearman connected components at 0.85: `[['co_movement'], ['directional_synchronization'], ['industry_liquidity_diffusion', 'liquidity_activity', 'liquidity_participation'], ['turnover_level'], ['liquidity_concentration'], ['liquidity_change']]`.

Components diagnose redundancy only. A stable role is not a panic mechanism or a useful trading state. Failed fixed representations leave their broader economic families open.

## Reproducibility

- Spec SHA-256: `56407172efc49cf306391824718c194c86844fb24065597b952b94b97469d9fd`
- CY-006 manifest SHA-256: `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`
- Panel SHA-256: `d45993ceb0a1d28d23ff9c7f10552890f82629f4d63b729a9bd73a9101a6e573`
