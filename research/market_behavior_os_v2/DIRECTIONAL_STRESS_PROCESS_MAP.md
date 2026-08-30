# Directional Synchronization/Stress Process Map

Frozen before MKT-DSTRESS-001 construction. This is a strategy-independent,
outcome-blind process map built only from frozen continuous coordinates. It does
not rescue the rejected MKT-SHOCK-001 all-three 0.90/0.50 episode and does not
use that experiment's failed onset, dwell, relief, or impairment fields.

## Why this process is distinct

MKT-SHOCK-001 synchronization pressure is direction-neutral. MKT-RISK-001 now
freezes central direction and separate upside/downside extreme participation.
The present question is whether synchronization plus signed extreme breadth has
a stable recurring geometry and causal episode shape. High activity is retained
as a modifier; it cannot define price direction.

## Frozen continuous representations

All components are strictly historical 3-year percentiles after at least 504
observations within each view/denominator.

| Concept | Primary score | Fixed aggregation neighbors | Fixed signed-definition neighbors | Boundary |
|---|---|---|---|---|
| Downside directional synchronization | minimum of synchronization pressure and downside-70 extreme-participation percentile | geometric and arithmetic means | minimum using downside-50 and downside-90 causal percentiles | synchronized downside tail breadth, not panic |
| Upside directional synchronization | minimum of synchronization pressure and upside-70 extreme-participation percentile | geometric and arithmetic means | minimum using upside-50 and upside-90 causal percentiles | synchronized upside tail breadth, not speculative payoff |
| Directional synchronization balance | upside score minus downside score | corresponding geometric and arithmetic differences | corresponding 50/90 differences | deterministic signed summary; never an independent mechanism |
| Activity modifier | frozen 20-session own-history-relative liquidity-activity percentile | fixed 10/60 activity percentiles | none | activity, not order side or liquidity supply |
| Broad-direction modifier | frozen central signed-limit-utilization percentile | expanding percentile and robust z retained | none | context only; not part of primary score |

Threshold-50/70/90 refers to the already-frozen security-level limit-utilization
definitions. MKT-DSTRESS-001 causally normalizes the absolute 50 and 90
cross-sectional fractions exactly as it does the accepted 70 definition. No
threshold or historical window is optimized.

## Fixed recurring process state machine

For upside and downside independently within each view/denominator:

1. when inactive, primary directional score `>=0.80` creates `ONSET`;
2. while active, score `>=0.80` is `ELEVATED` and score in `[0.50,0.80)` is
   `RELIEF`;
3. score `<0.50` resets the episode to `NORMAL`;
4. dwell is causal sessions since onset and relief is causal episode-peak minus
   current score;
5. activity `>=0.80` inside an active episode is `HIGH_ACTIVITY`, an explicit
   modifier rather than part of onset;
6. missing score breaks the episode with no carried state.

This is an elevated recurring-process definition, not a shock threshold. Its
fixed configurations are:

- permissive: entry 0.70, reset 0.40, high activity 0.70;
- primary: entry 0.80, reset 0.50, high activity 0.80;
- strict: entry 0.90, reset 0.60, high activity 0.90.

No configuration may replace a failed primary. The MKT-SHOCK-001 rejected
joint-score episode is neither a neighbor nor a candidate.

## Frozen gates

Continuous scores require at least 95% common post-warm-up coverage and 700
observations per group; median within-group Spearman at least 0.70 against every
aggregation/signed-definition neighbor; ALL_STATUS/NON_ST median Spearman at
least 0.90; nondegenerate eligible view-year cells; and no median absolute
Spearman at least 0.85 with any single corresponding signed primitive,
synchronization pressure, joint activity stress, or accepted volatility role.

Each side's primary process separately requires at least eight onsets in every
group across at least three years; onset matching within two sessions at least
0.50 against both configurations; ELEVATED and RELIEF state Jaccard each at
least 0.50; and median common-active-date Spearman at least 0.70 for dwell and
relief against both. High-activity modifiers require at least five observations
in two years per group and event Jaccard at least 0.30. A failed side or process
role cannot inherit acceptance from the other side.

## Interpretation boundary

A passed continuous role is a stable directional synchronization coordinate. A
passed state machine is a recurring elevated-process representation. Neither
establishes forced selling, speculative demand, price recovery, forecastability,
strategy habitat, or a trading rule. No future return, strategy outcome, failed
MKT-SHOCK episode field, or CY-011 input is permitted.
