# Industry leadership, rotation, and relative-strength representation map

Frozen before MKT-INDRS-001 construction. This is a strategy-independent
Market State family. It does not reproduce the rejected MA20 industry-diffusion
or breadth-divergence representations under new names.

## Representation roles

| Role | Primary | Fixed neighbors | Economic distinction |
|---|---|---|---|
| `industry_positive_participation_1d` | equal-industry fraction with median member 1d return >0 | mean member return >0; positive-member majority | same-session industry participation, not MA state |
| `industry_return_depth_1d` | median across industry median 1d returns | mean of industry medians; median of industry means | central equal-industry return depth |
| `industry_return_dispersion_1d` | p75-p25 of industry median 1d returns | p90-p10; median absolute deviation | cross-industry same-day disagreement |
| `industry_market_rs_depth20` | median industry median 20d return minus stock-weighted median 20d return | equal-industry mean minus stock mean; industry p60 minus stock p60 | equal-industry versus market relative strength |
| `industry_leadership_concentration20` | top-3 positive industry-return mass share | top-5; top-10 | concentration among leading industries |
| `winner_industry_diffusion20` | normalized industry entropy among top-decile stocks by 20d return | top 5%; top 20% | whether stock winners diffuse across industries |
| `industry_leadership_persistence20` | Jaccard overlap of top-5 industries now versus five sessions earlier | top-3; top-10 | persistence of industry leaders |
| `industry_rank_rotation20` | `(1-Spearman)/2` for current versus lag-5 industry return ranks | `(1-Kendall)/2`; mean absolute percentile-rank displacement | broad rank rotation, not only top leaders |
| `stock_industry_rs_dispersion20` | p75-p25 of stock minus leave-one-out industry-median 20d return | p90-p10; median absolute deviation | within-industry relative-strength breadth |
| `stock_industry_rs_tail_balance20` | p90+p10 of leave-one-out residual | p80+p20; p95+p05 | asymmetry of within-industry leaders versus laggards |
| `stock_industry_rs_concentration20` | top-decile positive residual-mass share | top 5%; top 20% | concentration of stock leadership after industry removal |

One-day roles capture current diffusion; 20-session roles capture relative
leadership structure. The fixed five-session comparison in persistence/rotation
is a state lookback, not a future outcome. No alternative horizon may rescue it.

## Construction and representation gates

- exact CY-006 core, PIT membership, view, denominator, mapping, member, and
  industry-count gates from the data contract;
- at least 95% raw coverage after the common 120-session warm-up;
- worst median Spearman across both fixed neighboring definitions at least
  0.70;
- ALL_STATUS versus NON_ST median Spearman at least 0.90;
- every eligible 2019-2023 view/year cell has at least 150 observations and is
  nondegenerate;
- expected causal PIT and relative-coordinate coverage;
- pairwise absolute Spearman graph at 0.85, with economic role priority in the
  table order for minimal-panel compression;
- external redundancy against frozen stock leadership concentration and breadth
  discovery/concentration roles at 0.85;
- two byte-identical serial runs.

Stable but redundant roles remain evidence about a latent mechanism. A failed
primary cannot be replaced by a favorable neighbor, view, year, denominator,
or related role.

## Claim boundary

Passing establishes a portable industry/relative-strength state coordinate,
not persistence into future returns, stock selection alpha, a sector-rotation
strategy, habitat fitness, causality, or usefulness. Those require separate
outcome and execution contracts after representation quality and compression.
