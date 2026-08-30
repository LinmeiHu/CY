# Industry leadership dynamics map

Frozen before MKT-INDRS-DYN-001 constructs any future state. This is a
strategy-independent temporal-process study. It reads no market return, stock
selection outcome, strategy field, or execution result.

## Mechanism question

MKT-INDRS-GEO-002 establishes that winner-industry diffusion and broad industry
rank rotation are distinct contemporaneous coordinates. It does not establish
whether they form a recurring leadership process. Three directed edges are
fixed:

1. `rotation_persistence`: current five-session rank rotation -> rank rotation
   in the immediately following nonoverlapping five-session block;
2. `diffusion_to_rotation`: current winner-industry diffusion -> next-block
   rank rotation, incremental to current rotation and broad leadership state;
3. `rotation_to_diffusion_change`: current rank rotation -> five-session change
   in winner-industry diffusion, incremental to current diffusion and broad
   leadership state.

The signs are not assumed. A positive first edge would mean rotation clusters;
a negative edge would mean stabilization. The cross-edges would distinguish
diffusion preceding migration from migration broadening/narrowing the winner
set. Null results leave both coordinates descriptive.

## Exact response semantics

Within each market view and denominator, every source row is one exchange
session. At decision date `t`:

- `next_block_rank_rotation5` is the frozen raw/PIT/relative rank-rotation
  coordinate at row `t+5`; its underlying rank comparison is `t` versus `t+5`,
  adjacent to but nonoverlapping with the current `t-5` versus `t` block;
- `future_winner_diffusion_change5` is winner-diffusion coordinate at `t+5`
  minus its value at `t` in the same coordinate system.

The response is available only at the completed `t+5` close. No response is an
entry predictor at `t`. Group tails without five later sessions are missing.

## Fixed controls

| Edge | Predictor | Response | Current controls |
|---|---|---|---|
| rotation persistence | rank rotation | next-block rank rotation | broad leadership concentration; co-movement; volatility change |
| diffusion to rotation | winner diffusion | next-block rank rotation | current rank rotation; breadth discovery; broad leadership concentration |
| rotation to diffusion change | rank rotation | future winner-diffusion change | current winner diffusion; breadth discovery; broad leadership concentration |

Controls are fixed before response construction. None may be removed because a
raw association is stronger. Equal-industry participation and residual
dispersion are excluded because external geometry already compressed them.

## Coordinate and validation design

Each edge is evaluated in four separately preserved coordinate systems: raw
absolute, causal trailing-three-year percentile, view-minus-ALL_A, and governed-
view rank. Raw and PIT effects are estimated within all eight view/denominator
groups. Relative effects pool the three non-ALL_A views or all four rank views
within each denominator, following the frozen cross-sectional geometry method.

- Discovery: predictor and response dates both within 2019-2021.
- Untouched confirmation: predictor and response dates both within 2022-2023.
- Primary block: all valid dates.
- Mandatory overlap diagnostic: phase-zero every-fifth predictor date within
  each group/block, so adjacent five-session responses do not overlap.

Partial Spearman is Pearson correlation of rank-residualized predictor and
response after the fixed current controls. No link function, sign, threshold,
horizon, phase, view, or year is selected after results.

## Frozen gates

An edge freezes only when all primary conditions pass:

- raw median absolute partial rho at least 0.10 in discovery and confirmation;
- raw median sign agrees across blocks and confirmation magnitude is at least
  half discovery magnitude;
- at least six of eight raw groups share the median sign in each block;
- raw phase-zero median absolute partial rho at least 0.08 in each block, with
  the same sign;
- causal-PIT median absolute partial rho at least 0.08 in each block, same sign
  as raw, with at least six of eight groups supporting it;
- view-minus-ALL_A and relative-rank median absolute partial rho at least 0.05
  in each block, with both denominator groups sharing the raw sign;
- at least 150 observations per raw/PIT group/block and 450/600 per pooled
  relative-to-all/relative-rank denominator/block.

Failure of any required coordinate, block, support, sign, or nonoverlap gate
rejects that exact temporal edge. No favorable coordinate, phase, edge, or
subset rescues another.

## Claim boundary

Passing would establish a replicating outcome-blind leadership-state dynamic,
not return prediction, stock-selection alpha, industry rotation timing, a
habitat, causality, or a trading rule. Strategy research would still require a
separate outcome/execution contract. CY-011 remains locked and unopened.
