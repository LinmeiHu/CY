# MKT-FORMDEPTH-ATTR-001 mechanism attribution

## Decision

`INCREMENTAL_OBJECTIVE_FORMATION_TAIL_RISK`

This is a same-day market-state attribution result, not a causal claim, entry
predictor, habitat, signal, trade, or strategy rule. The joint information clock
is 15:30 and every response starts on the next exchange session.

## Frozen-support audit

- joined economic rows: 11,296
- complete five-control rows: 6,631
- minimum complete rows per cell: 828
- cells: 8
- years: [2018, 2019, 2020, 2021, 2022, 2023]

The originally drafted 10,000-row complete-support floor was corrected to 6,500
before any response estimate because the mandatory causal discovery and volatility
controls begin later than the raw panels. No control, response, horizon, gate, or
classification was changed.

## Directness geometry

- maximum absolute same-cell pairwise Spearman: 0.534171
  (gate < 0.85)
- median same-cell joint adjusted rank R2: 0.256596
  (gate <= 0.70)
- geometry gate: **PASS**

## Extended-control downside response

- median h=3 PIT partial rho: -0.110530
- negative cells: 8/8
- h=1 median partial rho: -0.090172
- h=5 median partial rho: -0.117525
- block medians: {'A': -0.15387901772909232, 'B': -0.11920159210991478}
- supported-year medians: {'2020': -0.15387901772909232, '2021': -0.01648562830042564, '2022': -0.07312259034441937, '2023': -0.24564669292868738}
- supported-year leave-one-out medians: {'2020': -0.11920159210991478, '2021': -0.13579341105536136, '2022': -0.15772515604603587, '2023': -0.036767708180819036}
- h=3 phase signs: [-1, -1, -1]
- h=5 phase signs: [-1, -1, -1, -1, -1]
- median controlled high-minus-low PIT-tail residual gap: -0.005026

- `primary_size_and_sign`: **PASS**
- `same_sign_cells`: **PASS**
- `blocks`: **PASS**
- `years`: **PASS**
- `leave_one_year_out`: **PASS**
- `neighbors`: **PASS**
- `h3_phases`: **PASS**
- `h5_phases`: **PASS**
- `tail_residual_gap`: **PASS**

The narrower MKT-BREAKOUT-ECON-001 result remains an accurate result under its
pre-frozen discovery/volatility controls. This experiment only determines whether
that association remains incremental after central direction and ordinary same-day
return/range geometry are added. HAB-CHX-FORMDEPTH-001 already found no CHINEXT V1
habitat transfer, so no strategy action follows regardless of this classification.

CY-011, strategy fields, and post-2023 data were not read.
