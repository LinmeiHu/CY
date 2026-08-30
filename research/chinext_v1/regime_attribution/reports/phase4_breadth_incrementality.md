# Phase 4 — breadth incrementality falsification

## Decision

`SUPPORTED_INCREMENTAL_WITH_QUALIFICATION`. This remains exploratory mechanism evidence, not a strategy rule or untouched OOS result.

## Evidence

| Breadth feature | Best outcome | Partial rho | LOYO same sign | Positive trend strata | Pass |
|---|---|---:|---:|---:|---|
| breadth_above_ma20 | mfe | 0.18299672843847212 | 8/8 | 5/5 | YES |
| breadth_positive_return20 | mfe | 0.16410569676984446 | 8/8 | 4/5 | YES |
| breadth_above_ma20_change20 | mfe | 0.20522244575156837 | 8/8 | 5/5 | YES |

## Falsification

The model uses only the three frozen trend controls and entry-year effects. LOYO and fixed trend-stratum comparisons were required; no alternative control set, interaction, threshold, or overlay was searched.

## Strategy candidate

None. Incremental association does not establish portfolio improvement or a safe exposure rule.
