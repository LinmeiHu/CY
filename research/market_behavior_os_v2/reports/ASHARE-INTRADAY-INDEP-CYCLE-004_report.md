# Stock-level intraday alpha and independent discovery

Status: `COMPLETE_FROZEN_TWO_TRACK_DISCOVERY`.

The shared causal domain contains 624,918 eligible rows, 4,820 symbols, and 267 weekly decisions. All signals use completed-session CY008 summaries available at 15:30 and enter no earlier than the next market open. Track-A selection is the same-date cross-sectional residual after three frozen daily controls.

## Cheap screens

| Track | Family | Mechanism | Eligible | Dates | Median breadth | Max daily-control correlation | Full excess | Early | Late | Severe disadvantage | Role | Decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| A | vwap_acceptance | completed-session demand acceptance above VWAP | 624,918 | 267 | 2473 | 0.613 | -0.2175% | -0.2871% | -0.1573% | 5.1135% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | closing_acceptance | late-session demand | 624,918 | 267 | 2473 | 0.215 | -0.4178% | -0.5887% | -0.2696% | 5.3918% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | opening_weakness_recovery | early supply absorbed by the close | 136,828 | 267 | 439 | 0.532 | -0.2869% | -0.2941% | -0.2807% | 1.2728% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | late_volume_confirmed_demand | late demand confirmed by participation | 624,918 | 267 | 2473 | 0.366 | -0.4629% | -0.8777% | -0.1031% | 4.5774% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | intraday_volatility_contraction | recent supply/demand conflict contraction | 624,918 | 267 | 2473 | 0.353 | -0.2821% | -0.4851% | -0.1053% | 6.8868% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | relative_intraday_strength | stock demand versus same-industry peers | 600,489 | 267 | 2392 | 0.499 | -0.2774% | -0.2706% | -0.2833% | 5.2202% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| A | quiet_vwap_acceptance | VWAP acceptance without high intraday conflict | 624,918 | 267 | 2473 | 0.475 | 0.0886% | 0.1067% | 0.0729% | -0.2881% | STANDALONE_ALPHA | PROMOTE_EXECUTABLE |
| B | industry_leadership_acceleration | improving industry leadership | 572,539 | 266 | 2287 | 0.127 | 0.5363% | 0.6126% | 0.4709% | 1.5251% | COMPLEMENTARY_INFORMATION | NO_EXECUTABLE_REPLAY |
| B | industry_diffusion_acceleration | broadening industry participation | 572,539 | 266 | 2287 | 0.107 | 0.9662% | 0.7287% | 1.1705% | -3.4832% | STANDALONE_ALPHA | PROMOTE_EXECUTABLE |
| B | residual_mean_reversion_5 | short-lived stock underperformance versus peers | 600,489 | 267 | 2392 | 0.321 | 0.0402% | -0.2059% | 0.2531% | 3.5595% | CONDITIONAL_INFORMATION | NO_EXECUTABLE_REPLAY |
| B | liquidity_recovery | turnover withdrawal followed by positive demand recovery | 301,415 | 267 | 1040 | 0.245 | -0.1119% | -0.0355% | -0.1781% | 4.5094% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |
| B | down_market_resilience | relative demand on adverse market days | 299,437 | 128 | 2474 | 1.000 | -0.8385% | -1.4928% | -0.2811% | 14.3289% | NO_USEFUL_EVIDENCE | NO_EXECUTABLE_REPLAY |

## Frozen executable replays

| Family | Classification | Total | Annualized | Max DD | Sharpe | Severe | Turnover | Mean names | Mean industries | Capacity p10 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| quiet_vwap_acceptance | REPLAY_BLOCKED | — | — | — | — | — | — | — | — | — |
| industry_diffusion_acceleration | PROMISING_BUT_MIXED | 13.10% | 2.37% | -32.66% | 0.217 | 16.20% | 150.55x | 39.4 | 9.4 | CNY 101,576,172 |

Post-2023 outcomes and CY011 were not accessed. Industry Diffusion, Low Idiosyncratic Volatility, the CHINEXT RS veto, minute-volatility overlay, Industry Rotation, and resource-parked dispersion were not modified or retuned.
