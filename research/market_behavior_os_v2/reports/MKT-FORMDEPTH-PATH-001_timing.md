# MKT-FORMDEPTH-PATH-001 adverse-path timing

## Decision

`MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH`

This is daily-bar response attribution only. Future opens, lows, trough
sessions, and recovery fields are not predictors or executable signals.

## Fixed support

- complete five-control rows: 6,627
- minimum rows per cell: 826
- joint information clock: 15:30 Asia/Shanghai

## Classifying channels

### PREOPEN_PATH_DOWNSIDE

- gate: **PASS**
- h=3 median PIT partial rho: -0.263379
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.08187006565653568, '5': -0.29095899935714176}
- block medians: {'A': -0.19274546457224281, 'B': -0.2787102126378983}
- supported-year medians: {'2020': -0.19274546457224281, '2021': -0.08990380511180307, '2022': -0.2798535765325203, '2023': -0.4576971845202439}
- closing-arm h=3 medians: {'accepted': -0.18488862151671143, 'rejected': -0.27023295447890977}
- median controlled PIT-tail residual gap: -0.009570
- checks: {'primary': True, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True, 'closing_arms': True}

### TROUGH_SESSION_INTRADAY_DOWNSIDE

- gate: **PASS**
- h=3 median PIT partial rho: -0.406433
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.4082961826493263, '5': -0.41469605698000583}
- block medians: {'A': -0.17702932539983113, 'B': -0.427722579638957}
- supported-year medians: {'2020': -0.17702932539983113, '2021': -0.32602452734404974, '2022': -0.3566931344922215, '2023': -0.5822744144078951}
- closing-arm h=3 medians: {'accepted': -0.3642569666575419, 'rejected': -0.34708254374898234}
- median controlled PIT-tail residual gap: -0.007289
- checks: {'primary': True, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True, 'closing_arms': True}

## Diagnostics

- recovery h=3 median partial rho: 0.390991
- recovery h=1/h=5: {'1': 0.33557231003712085, '5': 0.35413479051682906}
- terminal: {'1': -0.028862755233619863, '3': -0.04662659449204511, '5': -0.052628154419041256}

Recovery and terminal response cannot promote or rescue a timing
classification. No strategy fields, post-2023 data, or CY-011 were read.
