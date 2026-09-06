# Phase 6 — Conditional Relationships

OC-EXP-P6-001: **PASS**. All breadth terms remain continuous; no threshold or overlay was tested.

## Breadth and market opportunity dispersion

| Daily dispersion field | N | rho(year) | Year + / - | LOYO + / - |
|---|---:|---:|---:|---:|
| cross_sectional_return20_std | 1758 | 0.264 | 8 / 0 | 8 / 0 |
| cross_sectional_return20_p90_p10_spread | 1758 | 0.308 | 8 / 0 | 8 / 0 |
| cross_sectional_return20_right_tail_ge20 | 1758 | 0.756 | 8 / 0 | 8 / 0 |

Tested 27 continuous Breadth x causal-stock-feature interactions; `0` pass the combined effect/yearly/LOYO/BH gate.

| Strongest interaction | Outcome | N | rho | q(27) | Year + / - | LOYO + / - |
|---|---|---:|---:|---:|---:|---:|
| breadth x entry_box_width | false_breakout | 387 | 0.116 | 0.669 | 5 / 3 | 8 / 0 |
| breadth x entry_minvol_location | false_breakout | 387 | -0.058 | 0.845 | 1 / 7 | 0 / 8 |
| breadth x entry_mom60 | mfe | 387 | 0.056 | 0.845 | 5 / 3 | 8 / 0 |
| breadth x entry_rs_score | right_tail_classification | 387 | 0.055 | 0.845 | 4 / 4 | 8 / 0 |
| breadth x entry_mom120 | false_breakout | 387 | 0.050 | 0.845 | 4 / 4 | 8 / 0 |
| breadth x entry_mom20 | right_tail_classification | 387 | -0.050 | 0.845 | 3 / 5 | 0 / 8 |
| breadth x entry_box_width | mfe | 387 | -0.048 | 0.845 | 3 / 5 | 0 / 8 |
| breadth x entry_box_width | right_tail_classification | 387 | -0.047 | 0.845 | 5 / 3 | 0 / 8 |
| breadth x entry_vol_ratio | mfe | 387 | 0.047 | 0.845 | 6 / 2 | 8 / 0 |
| breadth x entry_vol_ratio | right_tail_classification | 387 | 0.045 | 0.845 | 6 / 2 | 8 / 0 |
| breadth x entry_rs_score | false_breakout | 387 | 0.045 | 0.845 | 6 / 2 | 8 / 0 |
| breadth x entry_mom120 | mfe | 387 | -0.038 | 0.845 | 5 / 3 | 0 / 8 |

Path-context relations remain outcome diagnostics. Calendar-quarter and dispersion conditioning are reported in the machine-readable artifact; no cohort is selected as a rule.
