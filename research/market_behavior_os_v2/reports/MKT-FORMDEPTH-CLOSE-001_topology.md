# MKT-FORMDEPTH-CLOSE-001 closing-state topology

## Decision

`ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE`

This is closing-state-resolved market association topology only. It is
not causal, an entry predictor, terminal reversal, habitat, or a rule.

## Fixed support

- complete five-control rows: 6,627
- minimum rows per cell: 826
- joint information clock: 15:30 Asia/Shanghai

## Downside channels

### ACCEPTED_CROSSER_DOWNSIDE

- gate: **PASS**
- h=3 median PIT partial rho: -0.320860
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.26008984067668217, '5': -0.33035800652508074}
- block medians: {'A': -0.17860646152738596, 'B': -0.33569652093972535}
- supported-year medians: {'2020': -0.17860646152738596, '2021': -0.14534101647036557, '2022': -0.31799766323871526, '2023': -0.5167118469317431}
- median controlled PIT-tail residual gap: -0.016226
- checks: {'primary': True, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True}

### REJECTED_CROSSER_DOWNSIDE

- gate: **PASS**
- h=3 median PIT partial rho: -0.355714
- negative cells: 8/8
- h=1/h=5 medians: {'1': -0.38724534179731307, '5': -0.3415129681727074}
- block medians: {'A': -0.22784639852652683, 'B': -0.3794988102360965}
- supported-year medians: {'2020': -0.22784639852652683, '2021': -0.21809582184450654, '2022': -0.33713551548159454, '2023': -0.5354305909877847}
- median controlled PIT-tail residual gap: -0.015775
- checks: {'primary': True, 'cells': True, 'blocks': True, 'years': True, 'leave_one_year_out': True, 'neighbors': True, 'h3_phases': True, 'h5_phases': True, 'tail_gap': True}

### REJECTED_MINUS_ACCEPTED

- gate: **FAIL**
- h=3 median PIT partial rho: -0.007056
- negative cells: 4/8
- h=1/h=5 medians: {'1': -0.0985327986014326, '5': 0.024062592398534168}
- block medians: {'A': -0.08577701888248424, 'B': -0.003895695806612003}
- supported-year medians: {'2020': -0.08577701888248424, '2021': -0.11327149037653791, '2022': 0.0034035380401601254, '2023': 0.12204955155064799}
- median controlled PIT-tail residual gap: 0.000138
- checks: {'primary': False, 'cells': False, 'blocks': True, 'neighbors': False, 'tail_gap': False}

## Terminal diagnostics

{'REJECTED_CROSSER_DOWNSIDE': {'1': -0.05312999763471726, '3': -0.06503290823228766, '5': -0.054517644868124854}, 'ACCEPTED_CROSSER_DOWNSIDE': {'1': -0.018162629322927386, '3': -0.021583949474994507, '5': -0.035133544809572405}}

Terminal responses are diagnostic-only and cannot rescue a downside
classification. Equality was conserved but not economically estimated.
No strategy fields, post-2023 data, or CY-011 were read.
