# ASHARE-TRUE-GAP-BELOW-L-V26-V27-UNION-V1

`V26_V27_UNION_CAUSAL_IMPLEMENTATION_VALID`

## Frozen strategy

One V13 base population; admit when V26 OR V27 passes; deduplicate GAP_ID; replay both branches in one shared Main/ChiNext K80 portfolio. No branch priority exists.

`V13_BASE AND ((gap_width_pct <= 3% AND pre_gap_corridor_touch_sessions <= 10) OR (pre_peak_to_gap_sessions >= 20 AND gap_age <= 14 AND max_depth-current_depth >= 5% of L))`.

V13 base keeps the exact 120-session/120x241-minute pre-gap history, true downward gap, no L touch before signal, 10% maximum depth, 5% signal depth, first completed prior-high reversal, next legal minute-open entry with 5% net headroom to L, A67 target, H20, no stop and 40 bp round-trip cost.

|Period|Trades|Per year|Mean|Median|Win|Severe10|Total return|MaxDD|Sharpe|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|OBSERVED_2017_2023|636|90.86|4.12%|5.75%|77.20%|8.49%|17.56%|-2.83%|1.284|
|DIAGNOSTIC_2024_2025|159|79.50|5.68%|6.01%|82.39%|7.55%|5.72%|-0.98%|1.713|

## Signal-year trade results

|Year|Trades|Mean|Median|Win|Severe10|
|---:|---:|---:|---:|---:|---:|
|2017|58|1.73%|4.62%|67.24%|8.62%|
|2018|300|5.00%|6.68%|83.33%|8.67%|
|2019|72|4.88%|5.11%|79.17%|1.39%|
|2020|42|1.21%|3.70%|61.90%|16.67%|
|2021|65|4.11%|5.89%|76.92%|9.23%|
|2022|72|4.24%|6.11%|76.39%|11.11%|
|2023|27|1.65%|0.25%|51.85%|3.70%|
|2024|110|6.85%|7.52%|83.64%|8.18%|
|2025|49|3.04%|4.40%|79.59%|6.12%|

## Causality audit

Verdict: `NO_FORWARD_INFORMATION_DETECTED`.

Every union signal was recomputed from a daily prefix ending at its own signal close. True-gap identity, 120-session history, pre-gap corridor, peak age, gap age, depth, no-L-touch, and first prior-high reversal all matched. Entry must be a legal minute open strictly after the signal. Portfolio ranking uses only entry-time information.

Observed raw union signals: `815`; 2024-2025 diagnostic raw union signals: `181`. Each row passed 27 explicit causal, lineage, feature, branch and entry checks.

Blocking audit items: `0`.

Future bars are used only after executable entry to determine target realization, H20 exit, T+1 tradability and corporate-action-safe execution. They never create or admit a signal.

## Scientific limitation

The union was defined after both component results were observed. This confirms implementation causality, not a new external validation claim.
