# Breadth Representation Map

Frozen before MKT-BRTH-001 construction. This map describes the market and does
not select a strategy, outcome, state boundary, or trading rule.

## Boundary from prior H-004 work

The prior breadth artifact used the exact CHINEXT V1 membership and
basic-eligibility denominator, reset security histories at strategy replay
blocks, and later associated selected measures with admitted V1 entries. That
work remains valid archaeology, but it is not a strategy-independent market
breadth state.

MKT-BRTH-001 instead uses all registered CY-006 A-share daily rows that satisfy a
market-level causal price/history contract. It uses no V1 membership, signal,
entry, trade, return, MFE, MAE, exit, or outcome-class field.

## Representation families

All primary values are absolute, economically interpretable quantities. The
fixed neighbors test definition stability; they are not a window search.

| Concept | Economic question | Primary absolute representation | Fixed neighboring definitions | Candidate latent role |
|---|---|---|---|---|
| Participation | How much of the market is in an established positive price state? | fraction above causal MA20 | fractions above MA10 and MA60 | participation level |
| Breadth depth | How far is the typical security from its trend reference, not merely on which side? | median `adjusted_close / MA20 - 1` | median distance to MA10 and MA60 | participation depth |
| New-high/new-low participation | Is price discovery dominated by expansion or breakdown? | fraction at inclusive 60-session high minus fraction at inclusive 60-session low | net 40- and 80-session high/low participation | directional participation intensity |
| Breadth momentum | Is recent cross-sectional price movement broadly positive or negative? | mean sign of causal 5-session return | mean signs of 3- and 10-session returns | short-horizon participation |
| Breadth acceleration | Is participation improving faster or deteriorating faster? | second 5-session difference of MA20 participation | second 3- and 10-session differences | transition curvature |
| Industry diffusion | Is participation distributed across industries rather than confined to securities in a few groups? | equal-industry fraction whose member majority is above MA20 | MA10 and MA60 versions | diffusion |
| Leadership concentration | How much positive 20-session return mass is carried by a narrow leader set? | share of positive-return mass in the top return decile | top 5% and top 20% shares | leadership concentration |
| Breadth divergence | Does stock-count participation differ from equal-industry diffusion? | stock-weighted MA20 participation minus equal-industry MA20 diffusion | MA10 and MA60 differences | participation-versus-diffusion imbalance |
| Breadth transitions | Are more securities crossing into than out of an established positive state? | net fraction crossing MA20 over five sessions | three- and ten-session net crossing fractions | transition flow |

## Three coordinate systems

For every primary representation that passes construction:

1. **Absolute:** the raw fraction, return-mass share, or price-distance value.
   These remain the primary cross-year-comparable coordinates.
2. **Strict PIT historical context:** within-view expanding percentile, trailing
   756-session percentile, and trailing robust z-score, each including only
   completed observations through the same `decision_at` and requiring at least
   504 observations. Zero MAD remains missing.
3. **Relative view:** the contemporaneous view-minus-ALL_A value and the rank
   among available governed market views. Relative values never replace the
   absolute coordinate.

## Governed portability views

- `ALL_A`: all causally valid current A-share observations;
- `SH_A`: `.SH` observations;
- `SZ_A`: `.SZ` observations;
- `CHINEXT_BOARD`: historically valid `.SZ` symbols whose codes begin `300` or
  `301`.

Each view has an `ALL_STATUS` primary denominator and a `NON_ST` sensitivity
denominator. No liquidity threshold, V1 membership, present-day survivor list,
or strategy selection is used.

Exact historical constituent membership for CSI300, CSI500, CSI1000, and other
indices is not registered. Consequently, constituent-index breadth and literal
cross-index portability fail closed. Exchange/board portability is tested and
must not be described as constituent-index breadth.

## Industry semantics

Industry is usable only when `industry_valid=true`, the label is nonempty, and
`source_notice_date <= trade_date`. Daily view-level industry diffusion requires:

- at least 80% mapping coverage among the eligible view;
- at least five eligible members per included industry;
- at least ten included industries.

Industries are equal weighted after the member gate. Missing coverage produces
missing diffusion/divergence rather than a fallback label.

## Representation-quality gates

A concept is constructed before any economic-usefulness question and must report:

- semantic and PIT contract pass/fail;
- raw and normalized coverage by view/year/denominator;
- fixed neighboring-definition Spearman stability by view;
- ALL_STATUS versus NON_ST denominator stability;
- year-cell nondegeneracy and absolute-value support;
- exchange/board portability;
- complete pairwise primary redundancy;
- deterministic connected components at absolute Spearman `>=0.85` as an
  outcome-blind latent-mechanism diagnostic.

The fixed primary passes only if raw coverage is at least 95%, the worst median
neighbor stability is at least 0.70, all eligible view-year cells are
nondegenerate, and ALL_STATUS/NON_ST stability is at least 0.90. A failed primary
is not replaced by its best-looking neighbor inside the experiment.

Minimal-role compression follows the fixed order:

`participation, depth, new_high_low, momentum, industry_diffusion,
leadership_concentration, divergence, acceleration, transition`.

A passing role enters the minimal panel only when its absolute Spearman
correlation with every earlier accepted role is at most 0.85. Excluded concepts
remain documented representations; construction does not reject their broader
research families.

## Usefulness boundary

MKT-BRTH-001 may establish representation quality only. It cannot establish
forecasting value, habitat relevance, strategy usefulness, or a Trend x Breadth
interaction. Those questions require separately frozen experiments after both
dimensions have defensible representations.
