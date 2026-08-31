# MKT-BREAKOUT-ECON-001 economic market response

Status: **COMPLETE_SUPPORTED_MARKET_STATE_RESPONSE**.

This is pre-2024 strategy-independent market behavior. It is not a trading rule, strategy habitat, causal claim, or execution backtest.

## Role decisions

| role | status | retained tier | h3 return effect | h3 downside effect | placebo q | transition |
|---|---|---|---:|---:|---:|---|
| formation_participation | NO_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | -0.001282 | 0.002252 | 0.3483 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| formation_depth | TAIL_RISK_RESPONSE | SUPPORTED_MARKET_STATE | 0.000657 | -0.011116 | 0.0087 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| closing_acceptance | NO_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | 0.000232 | 0.000699 | 0.7430 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| closing_rejection_depth | UNSTABLE_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | 0.000071 | -0.006791 | 0.0087 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| formation_diffusion | NO_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | 0.002188 | 0.004779 | 0.0087 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| formation_leadership_concentration | NO_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | 0.000091 | -0.000372 | 0.9502 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |
| stock_industry_divergence | NO_ECONOMIC_RESPONSE | DESCRIPTIVE_ONLY | 0.003872 | 0.002936 | 0.0087 | TRANSITION_NOT_ESTIMABLE_FIXED_SUPPORT |

## Boundary

Supported market states: formation_depth.
Descriptive-only states: formation_participation, closing_acceptance, closing_rejection_depth, formation_diffusion, formation_leadership_concentration, stock_industry_divergence.
Up/down transition incrementality was not promoted unless the fixed episode support gate passed; insufficient support is not interpreted as no effect.

CY-011, post-2023 data, strategy outcomes, fills, P&L, and CHINEXT habitat fields were not read.
