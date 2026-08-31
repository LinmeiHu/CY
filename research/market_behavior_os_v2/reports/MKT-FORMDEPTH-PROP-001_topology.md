# MKT-FORMDEPTH-PROP-001 response topology

## Decision

`LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY`

This is membership-resolved market association topology only. It is not
causal, an entry predictor, a tradable arm portfolio, a habitat, or a rule.

## Fixed support

- complete five-control rows: 6,631
- minimum rows per cell: 828
- joint information clock: 15:30 Asia/Shanghai

## Downside channels

### CROSSER_DOWNSIDE

- gate: **PASS**
- h=3 median PIT partial rho: -0.383948
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.37891299467489326, '5': -0.37339795355079897}
- block medians: {'A': -0.24134284517062302, 'B': -0.40352673411178763}
- supported-year medians: {'2020': -0.24134284517062302, '2021': -0.2131660137497557, '2022': -0.36769883074831977, '2023': -0.5899259337455637}
- median controlled PIT-tail residual gap: -0.016952
- checks: {'primary': True, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True}

### NONCROSSER_DOWNSIDE

- gate: **FAIL**
- h=3 median PIT partial rho: -0.097696
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.07855871081849967, '5': -0.10617045242168272}
- block medians: {'A': -0.14392099085631854, 'B': -0.0994595561303592}
- supported-year medians: {'2020': -0.14392099085631854, '2021': -0.009246625275573288, '2022': -0.07018389403860754, '2023': -0.21921467756704266}
- median controlled PIT-tail residual gap: -0.004610
- checks: {'primary': False, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True}

### CROSSER_MINUS_NONCROSSER

- gate: **PASS**
- h=3 median PIT partial rho: -0.461767
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.3874603369031885, '5': -0.4643762641373472}
- block medians: {'A': -0.18380684125943614, 'B': -0.482637763295729}
- supported-year medians: {'2020': -0.18380684125943614, '2021': -0.3010975201624877, '2022': -0.4930794682306311, '2023': -0.6259492449666253}
- median controlled PIT-tail residual gap: -0.012509
- checks: {'primary': True, 'cells': True, 'blocks': True, 'neighbors': True, 'tail_gap': True}

## Terminal diagnostics

{'CROSSER_DOWNSIDE': {'1': -0.028862755233619863, '3': -0.04662659449204511, '5': -0.052628154419041256}, 'NONCROSSER_DOWNSIDE': {'1': -0.018594210750580327, '3': -0.030539583284743495, '5': -0.03054560225392266}}

Terminal responses are diagnostic-only and cannot rescue a downside
classification. HAB-CHX-FORMDEPTH-001 remains closed. Strategy fields,
post-2023 data, and CY-011 were not read.
