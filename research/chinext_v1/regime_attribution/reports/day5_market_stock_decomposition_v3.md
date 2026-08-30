# Day-5 market-versus-stock decomposition

EXP-D5D-003 decomposes the already-accepted H-013 day-5 landmark. It does not retest H-019 and does not create a holding or exit rule.

## Integrity and timing

- Accepted survivors/extreme winners/control-complete: `295` / `15` / `284`.
- All entry opens and exact fifth-session 399102 closes map one-to-one through the frozen calendar and anchor.
- Log-component reconstruction maximum absolute error: `1.11e-16`.
- AVAILABLE_AT_TIMESTAMP: `DAY5_SESSION_15:30_ASIA_SHANGHAI`.
- POTENTIAL_ACTION_TIMESTAMP: `NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION`.
- No post-exit price, counterfactual return, threshold, replay, or strategy rule is used.

## Frozen component tests

| Component | Raw rho | Raw LOYO + | Controlled rho | Controlled LOYO + |
|---|---:|---:|---:|---:|
| Stock-specific log excess | 0.223 | 8/8 | 0.283 | 8/8 |
| 399102 log return | 0.190 | 8/8 | 0.159 | 8/8 |
| Beta-adjusted stock excess | 0.055 | 7/8 | 0.132 | 8/8 |

The stock-specific controlled test includes the contemporaneous 399102 component plus frozen pre-entry V1, market, breadth, beta, liquidity, and year state. The market controlled test conditions on the stock-specific component and the same pre-entry state.

## Falsification

- Blocks: `{"DEVELOPMENT_2024_2025": {"n": 99, "p_value": 0.0021601217409178393, "rho": 0.3047752932367898}, "EXTENDED_2018_2021": {"n": 137, "p_value": 0.03508616570653675, "rho": 0.18021850778364648}, "HOLDOUT_O0_2022_2023": {"n": 59, "p_value": null, "rho": null}}`.
- Ex-Top4 P&L rho: `0.162`; duration/exit partial rho: `0.209`.
- Gates stock raw/control, market, neighbors, temporal, falsification: `True` / `True` / `True` / `False` / `False` / `True`.

## Scientific decision

`REFINE` / `STOCK_SPECIFIC_COMPONENT_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION`.

The decomposition is explanatory and outcome-overlapping. It cannot establish an ex-ante predictor or authorize an entry, hold, sell, sizing, or production modification.

The HOLDOUT block contains zero extreme winners, so its block rho is non-estimable and the frozen three-block temporal gate fails.
