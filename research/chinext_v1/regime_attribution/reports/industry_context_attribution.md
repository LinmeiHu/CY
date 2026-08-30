# Industry context decomposition of CHINEXT V1 right-tail entries

EXP-ICD-001 separates same-industry peer strength from stock-specific residual strength at the completed-close entry signal. It is exploratory mechanism evidence over consumed outcomes, not a filter or strategy experiment.

## PIT and sample audit

- All entries: `399`; fixed >=5-peer sample: `296`; extreme winners: `14`; winner20: `34`.
- PIT-valid industry labels in the fixed sample: `33`; peer count minimum/median: `5` / `14.0`.
- Mapping/PIT failures: `0` / `0`; strategy replays: `0`; post-entry prices: `0`.
- Peers are contemporaneously basic-eligible, share the entry security's source-notice-valid industry label, and exclude the entry security itself.

## Competing primary mechanisms

| Component | Raw rho | BH q | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Median neighbor | 60d neighbor | Pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| industry_market_relative20 | 0.065 | 0.524 | 0.053 | 7/8 | -0.041 | 0/8 | 0.065 | -0.038 | NO |
| stock_industry_residual20 | -0.029 | 0.619 | -0.033 | 2/8 | -0.094 | 0/8 | -0.003 | 0.137 | NO |

The fixed residual design controls the competing component, V1 entry RS/momentum/box/minimum-volume/breakout-volume state, market return/volatility, frozen breadth, trailing beta, traded-amount liquidity, peer count, and entry year.

## Active falsification

| Component | Ex-top-1% rho | Holding/exit rho | Security omission + | Industry omission + | >=10-peer rho | Falsification pass |
|---|---:|---:|---:|---:|---:|---|
| industry_market_relative20 | 0.026 | -0.041 | 1.000 | 1.000 | 0.155 | NO |
| stock_industry_residual20 | -0.030 | -0.100 | 0.000 | 0.030 | -0.066 | NO |

## Fixed outcome-class medians

| Outcome class | N | Industry-market relative20 | Stock-industry residual20 |
|---|---:|---:|---:|
| extreme_winner | 14 | 0.050 | 0.016 |
| ordinary_loser | 140 | 0.040 | 0.041 |
| ordinary_winner | 90 | 0.033 | 0.055 |
| severe_loser | 32 | 0.025 | 0.072 |
| strong_winner | 20 | 0.033 | 0.008 |

## Scientific decision

`REJECT` / `NEITHER_COMPONENT_SURVIVES`. Passing components: `none`.

No observed historical relationship is a threshold, filter, ranking change, or deployable rule. Industry labels are bounded PIT-B and all outcomes are consumed.

## Strategy candidate

None. EXP-ICD-001 authorizes no V1 modification.
