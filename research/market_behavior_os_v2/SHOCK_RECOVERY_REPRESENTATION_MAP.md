# Correlation/liquidity Shock-and-Recovery Representation Map

Frozen before MKT-SHOCK-001 construction. This map is strategy-independent and
outcome-blind. It distinguishes a high level from a shock, and stress relief
from price recovery. It does not presume panic, forced selling, impairment of
fundamental value, reversal, forecastability, or strategy usefulness.

## Why a new representation is required

MKT-CLQ-001 froze co-movement, directional synchronization, liquidity activity,
turnover, and amount concentration as contemporaneous levels. Its exact raw
five-session liquidity-activity change failed the 3/10-session neighboring-
horizon gate. MKT-SHOCK-001 may not tune or relabel that failed difference.

A shock is a path through state, not a high observation. The new construction
therefore uses a causal, windowless episode state machine driven by already-
frozen levels and their strictly historical PIT coordinates. Threshold and
aggregation neighbors are robustness tests, not search candidates.

## Representation map

| Concept | Economic question | Primary representation | Fixed neighbors | Claim boundary |
|---|---|---|---|---|
| Synchronization pressure | Are co-movement and same-direction synchronization jointly unusual versus their own histories? | minimum of their causal 3-year percentiles | geometric and arithmetic means | direction-neutral; not necessarily a selloff |
| Activity pressure | Is typical security amount unusually high versus its causal own-history-relative market state? | causal percentile of median current/prior-20 amount ratio | separately constructed prior-10 and prior-60 ratio percentiles | activity, not order-flow side or liquidity supply |
| Joint stress score | Are synchronization and activity simultaneously extreme? | minimum of co-movement, synchronization, and activity percentiles | geometric mean, arithmetic mean, and min with 10/60 activity neighbors | high joint state, not yet a shock onset |
| Shock onset | Did joint stress enter the extreme tail from outside an active episode? | causal state-machine entry at score >=0.90 | threshold configurations 0.85 and 0.95 | event representation only; no future path |
| Stress dwell | How long has the same stress episode remained unresolved? | causal sessions since onset until score resets below 0.50 | reset levels 0.45 and 0.55 paired with threshold neighbors | episode age, not damage |
| Stress relief | How far has current joint stress fallen from its causal episode peak? | episode peak-to-current score drawdown while active | same quantity under the two threshold/reset neighbors | synchronization/activity relief, not price recovery |
| Post-stress activity impairment | Has activity fallen into its lower tail while a stress episode is in relief? | recovery state and activity percentile <=0.10 | <=0.15 and <=0.05 under threshold neighbors | possible dry-up descriptor, not causal impairment |
| Turnover modifier | Does stress coincide with unusually high registered turnover? | frozen turnover-level causal percentile | absolute level and governed-view relative coordinate | modifier only; not part of onset definition |
| Concentration modifier | Is activity unusually concentrated during the episode? | frozen amount-concentration causal percentile | absolute share and governed-view relative coordinate | concentration is not breadth or participant identity |

## Primary causal state machine

For each market view and denominator independently:

1. `joint_stress_score = min(correlation_pct, synchronization_pct, activity_pct)`.
2. When inactive, score `>=0.90` creates `ONSET`, episode age one, and a causal
   episode peak equal to the current score.
3. While active, score `>=0.90` is `STRESS`; score in `[0.50,0.90)` is `RELIEF`.
4. Score `<0.50` closes the prior episode and is `NORMAL`; no episode value is
   carried forward.
5. A return above 0.90 during the same unresolved episode remains `STRESS`; it
   is not counted as a new onset.
6. `ACTIVITY_IMPAIRMENT` is a modifier inside `RELIEF` when the activity
   percentile is `<=0.10`.

All state at date `t` uses only completed data available at `t`. Episode peak,
age, and state are updated sequentially from past/current observations. No
future episode completion, subsequent return, or hindsight peak is used.

## Fixed neighboring configurations

- Permissive: onset/stress `>=0.85`, reset `<0.45`, impairment `<=0.15`.
- Primary: onset/stress `>=0.90`, reset `<0.50`, impairment `<=0.10`.
- Strict: onset/stress `>=0.95`, reset `<0.55`, impairment `<=0.05`.

Aggregation neighbors retain the primary 0.90/0.50/0.10 state thresholds and
replace the weakest-link minimum only with the geometric or arithmetic mean.
Activity-horizon neighbors retain the weakest-link minimum and replace only the
20-session activity ratio with fixed 10- or 60-session versions. None may rescue
a failed primary state.

## Coordinates and portability

The output preserves the raw absolute frozen inputs, their causal expanding/
three-year percentile and robust-z coordinates, and their governed-view
relative coordinates. Joint scores live on a causal percentile scale; they do
not replace the absolute components. Four views (`ALL_A`, `SH_A`, `SZ_A`,
`CHINEXT_BOARD`) and both `ALL_STATUS`/`NON_ST` denominators remain mandatory.

The primary normalized sample begins only when all three causal percentiles have
at least 504 observations. Missing or invalid state breaks an episode and emits
no inferred transition.

## Representation gates

1. all eight view/denominator groups retain at least 95% post-warm-up score
   coverage and at least 700 valid normalized observations;
2. the primary joint score has median within-group Spearman `>=0.70` versus
   every fixed aggregation and activity-horizon neighbor;
3. ALL_STATUS versus NON_ST primary-score median Spearman is `>=0.90`;
4. every eligible view-year cell with at least 100 observations is nondegenerate;
5. every group has at least eight primary onsets across at least three years;
6. primary onset matching within +/-2 sessions is `>=0.50` against both fixed
   threshold neighbors; primary STRESS and RELIEF state Jaccards are each
   `>=0.50` against both;
7. primary relief magnitude has median common-active-date Spearman `>=0.70`
   against both threshold neighbors;
8. accepted shock/recovery roles are compressed at absolute Spearman `0.85` and
   explicitly tested against frozen realized-volatility level, change, intraday
   range, and volatility concentration;
9. no failed state/neighbor is replaced, and no cutoff, horizon, or aggregation
   is optimized after construction.

## Interpretation boundary

The construction can freeze a direction-neutral synchronization/activity stress
process and its causal relief path. It cannot call the process panic without a
separately frozen negative-direction coordinate; it cannot call relief price
recovery; and it cannot establish future return, reversal, habitat, or strategy
usefulness. Those would require a later preregistered experiment.
