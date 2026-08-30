# Correlation and Liquidity Representation Map

Frozen before MKT-CLQ-001 construction. This map describes contemporaneous
market state. It does not define panic, reversal, impairment, a habitat, a
strategy, or an outcome.

## Economic separation

Correlation and liquidity are not one factor. Correlation describes how
securities move together; liquidity describes the level, distribution, and
change of current trading activity. A later panic hypothesis would have to
combine already-defensible roles under a separately frozen design.

| Concept | Economic question | Primary absolute representation | Fixed neighboring definitions | Candidate role |
|---|---|---|---|---|
| Co-movement | Are individual securities moving with their governed market view? | cross-sectional median 20-session correlation of each security's causal return with its leave-one-out equal-weight view return | 10- and 40-session correlations | co-movement level |
| Directional synchronization | Is same-direction movement persistent across recent sessions? | five-session mean of the daily stock-versus-leave-one-out-view sign concordance balance | three- and ten-session means | synchronization |
| Liquidity activity | Is the typical security trading above or below its own causal activity baseline? | median current amount divided by the prior-20-session mean amount | prior-10 and prior-60 baselines | activity level |
| Liquidity participation | How widely is above-baseline activity distributed? | fraction of securities whose amount exceeds their prior-20-session mean | prior-10 and prior-60 baselines | activity participation |
| Turnover level | What is the cross-sectional level of traded float? | median registered `turnover_fraction` | 40th and 60th percentiles | turnover level |
| Liquidity concentration | Is market trading value concentrated in a small security set? | share of current amount in the top amount decile | top 5% and top 20% shares | liquidity concentration |
| Industry liquidity diffusion | Is above-baseline activity distributed across industries? | equal-industry fraction whose member majority is above its prior-20-session amount mean | prior-10 and prior-60 versions | liquidity diffusion |
| Liquidity change | Is typical relative activity rising or falling? | five-session difference of median 20-session-relative activity | three- and ten-session differences | activity transition |

The neighbors are frozen robustness definitions, not a window or threshold
search. A failed primary is not replaced by its most favorable neighbor.

## Causal co-movement coordinate

For each governed view, denominator, and completed date, the leave-one-out view
return for security `i` is:

`(sum of valid security log-return steps - step_i) / (eligible_count - 1)`.

The security never appears in its own market reference. Rolling correlations
require 10, 20, or 40 consecutive exchange sessions. Missing sessions or
invalid causal coordinate steps invalidate the affected exact window. The
current completed close is allowed because the representation timestamp is the
same completed close; no later bar or future return is used.

Directional concordance is the cross-sectional mean of
`sign(security_step) * sign(leave_one_out_view_step)`. Zero returns contribute
zero, not an invented positive or negative direction.

## Causal liquidity coordinate

- `amount` is registered daily traded value in CNY. The activity ratios use the
  current completed amount divided by an exact prior-session mean that excludes
  the current date.
- `turnover_fraction` is used as registered. The input audit must establish
  finite nonnegative values and exact consistency with `turnover_pct / 100`
  before construction.
- No absolute CNY threshold, liquidity screen, market-cap proxy, float
  reconstruction, or present-day survivor rule is permitted.
- Raw total amount is retained only for conservation/audit; dimensionless
  activity ratios, fractions, turnover fraction, and concentration shares are
  the cross-year comparison coordinates.

## Coordinates, views, and gates

Each primary preserves:

1. its absolute dimensionless value;
2. strictly causal expanding percentile, trailing 756-session percentile, and
   trailing 756-session robust z-score, each with at least 504 observations;
3. same-date view-minus-ALL_A and governed-view rank where economically
   meaningful.

The fixed views and denominators are the breadth contract's `ALL_A`, `SH_A`,
`SZ_A`, and `CHINEXT_BOARD`, each under `ALL_STATUS` and `NON_ST`. These are
exchange/board portability views, not historical constituent-index breadth.
Industry diffusion retains the 80% causal-mapping, five-member, and ten-industry
minimums.

The primary construction gate requires at least 95% post-warm-up coverage, a
worst median neighboring-definition Spearman correlation of 0.70, median
ALL_STATUS-versus-NON_ST Spearman correlation of 0.90, and nondegenerate eligible
view-year cells. Outcome-blind absolute-Spearman components at 0.85 diagnose
redundancy; they do not prove causal latent mechanisms.

## Usefulness boundary

MKT-CLQ-001 may establish representation quality only. It cannot establish a
panic state, predict recovery, identify impairment, select a strategy, or show
economic usefulness. No future return, strategy membership, trade, or outcome
field is permitted.
