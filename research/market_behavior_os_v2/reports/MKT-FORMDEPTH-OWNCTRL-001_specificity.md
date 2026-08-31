# MKT-FORMDEPTH-OWNCTRL-001 objective specificity

## Decision

`OWN_EFFECT_NOT_INCREMENTAL_TO_FIXED_DAILY_GEOMETRY`

- Median h3 raw within-date rho: -0.272223
- Median h3 partial rho after five fixed t-day controls: -0.021750
- Median target rank R2 from controls: 0.511799
- Median controlled h3 top-minus-bottom depth-tail gap: -0.003116
- Negative cell medians: 8/8

- `support`: PASS
- `primary`: FAIL
- `cells`: PASS
- `blocks`: FAIL
- `years`: FAIL
- `leave_one_year_out`: PASS
- `neighbors`: PASS
- `h3_phases`: PASS
- `h5_phases`: PASS
- `controlled_tail_gap`: PASS

The controls are action-coordinate close return, intraday range, close location,
turnover fraction, and log traded-value scale. Traded value is not claimed to be
true liquidity. This is pre-2024 within-date association specificity only—not
causal supply, prediction, execution, payoff, habitat, or strategy.
