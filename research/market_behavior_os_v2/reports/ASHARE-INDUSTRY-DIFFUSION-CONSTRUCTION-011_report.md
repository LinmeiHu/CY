# Industry Diffusion stock-quality strategy construction

> Consumed 2018–2023 development evidence only. Post-2023 outcomes and CY-011 were not read.

## Baseline reproduction

The frozen `industry_diffusion_20` replay reproduces exactly: total 54.64%, annualized 8.60%, maximum drawdown -29.10%, Sharpe 0.440, Calmar 0.296, severe trades 18.46%, turnover 165.52x, and 2,627 completed trades.

## Candidate-level attribution

| Arm | Changed | Overlap | Quality coverage | Full payoff delta | Early / late delta | Severe improvement | Winner capture | Replay gate |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| arm1_upper_limit_clean | 64.72% | 35.28% | 88.01% | 0.416% | 1.083% / -0.159% | 0.818% | 2.347% | FAIL |
| arm2_low_max | 63.63% | 36.37% | 100.00% | 0.397% | 0.594% / 0.226% | 4.439% | 2.367% | PASS |

- `arm1_upper_limit_clean`: 267 dates, 1,728 changed selections, median 56 eligible stocks / 4 industries; net severe losers avoided 23, net winners captured 57, and aggregate positive-payoff sum sacrificed -7.634.
- `arm2_low_max`: 267 dates, 1,699 changed selections, median 56 eligible stocks / 4 industries; net severe losers avoided 117, net winners captured 59, and aggregate positive-payoff sum sacrificed +9.009.

Industry allocation counts are identical to baseline by construction; the diagnostic is within-industry and cannot create an industry-composition result.

## Full executable comparison

| Arm | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Turnover | Trades | Entry coverage | Positions | Industries | HHI | P10 capacity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| arm0_baseline | 54.64% | 8.60% | -29.10% | 0.440 | 0.296 | 18.46% | 165.52x | 2627 | 99.89% | 39.4 | 12.4 | 0.175 | CNY 111,580,500 |
| arm2_low_max | 122.43% | 16.34% | -25.77% | 0.731 | 0.634 | 14.13% | 210.52x | 2625 | 99.81% | 39.3 | 12.4 | 0.175 | CNY 111,124,306 |

Portfolio materiality:
- `arm2_low_max`: return delta +67.80%, drawdown improvement +3.32%, Sharpe delta +0.291, severe improvement +4.33%; materiality `FAIL`; failed: turnover.

## Complexity decision

Neither frozen stock-quality mechanism earned a permanent place. Preserve the baseline Industry Diffusion result as mixed and park further construction refinement absent new independent evidence.

Family-level classification: `STRATEGY_CONSTRUCTION_NOT_IMPROVED`.

## Next Price–Volume–Path questions

1. **Price-limit event lifecycle and acceptance** — After an objectively known limit-state event, which predeclared acceptance/rejection paths separate durable demand from temporary attention? Rationale: High economic value and existing historical-limit/minute data; materially different from another momentum lookback or limit-event count.
2. **Industry leader–follower convergence and leadership turnover** — Does causal convergence between leaders and followers forecast continuation or industry reversal beyond frozen diffusion level and acceleration? Rationale: Uses registered industry structure while asking a distinct mechanism question with broad opportunity breadth.
3. **Liquidity-transition shock assimilation** — Do predeclared turnover/liquidity state transitions distinguish informed continuation from temporary attention without repeating low-turnover levels? Rationale: Price-volume information remains underexploited at the transition layer and is cheap to test with existing data.
