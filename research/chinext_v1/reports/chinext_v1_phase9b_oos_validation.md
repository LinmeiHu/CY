# ChinNext V1 Phase 9B — frozen temporal holdout validation

Formal run order: O0_BASELINE -> O1_WINNER_HOLD (exactly once each).

## Frozen identities
- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- HOLDOUT_MANIFEST_SHA256: `4763562dac0538961b8fa5435b7a9475d92bc6e6562faca259b6429ff86bcb43`
- PHASE9B_SPEC_SHA256: `e2265b3a3fec2e809d88b69d1884faf3b27a78df47ad617fed1fe32c07e0602d`
- DATE_RANGE: `2022-01-04 .. 2023-12-29`; warmup `2021-07-08`
- Winner qualification: holding sessions >= 20 AND current return >= +20% on the market-exit decision day.

## Core metrics
| Arm | Total return | Annualized | Max DD | Sharpe | Trades | Win rate | Avg invested | Top20 | Ex-best20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| O0_BASELINE | -15.5221% | -8.1683% | -19.3413% | -0.6815 | 94 | 25.5319% | 17.8354% | 99.5826% | -33.7435% |
| O1_WINNER_HOLD | -17.4353% | -9.2250% | -21.1677% | -0.7784 | 94 | 25.5319% | 17.9619% | 99.5308% | -33.5724% |

Additional frozen metrics:

| Arm | Volatility | Median trade | Mean trade | 2022 return | 2023 return | Avg holdings | Top1 | Top5 | Top10 | Ex-best10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| O0_BASELINE | 11.5017% | -3.3237% | -1.6552% | -17.2914% | 2.1392% | 1.7996 | 15.9099% | 66.7996% | 88.9736% | -31.8023% |
| O1_WINNER_HOLD | 11.5463% | -3.3237% | -1.9226% | -17.2914% | -0.1740% | 1.8140 | 17.5601% | 62.7587% | 87.7007% | -31.6544% |

## O1 diagnostics
- MARKET_EXIT_POSITION_COUNT: `72`
- WINNER_QUALIFIED_AT_MARKET_EXIT_COUNT: `2`
- WINNER_DEFERRED_COUNT: `2`
- NORMAL_MARKET_EXIT_COUNT: `70`
- DEFERRED_EVENTUALLY_LOSER_COUNT: `0`

Per-episode return differences are descriptive only; portfolio paths differ after each market-exit decision.

## Comparison and generalization

- O1 minus O0 total return: `-1.9133 pp`; annualized return: `-1.0566 pp`; max drawdown: `-1.8263 pp` (worse); Sharpe: `-0.0969`.
- O1 minus O0 average invested fraction: `+0.1264 pp`; Top20 concentration: `-0.0517 pp`; return-ex-best20: `+0.1711 pp`; trade count delta: `0`.
- Year consistency: 2022 unchanged (`0.0000 pp`), 2023 negative (`-2.3133 pp`).
- Development direction (2024–2025 Phase 8) was positive on return and drawdown; OOS direction is not consistent.
- Winner-hold generalization: **NOT_SUPPORTED_OOS**; evidence strength: **WEAK**. The mechanism activated only twice, and both deferred episodes realized lower returns than baseline, with no eventual losers.
- No current-survivor fallback, PIT rebuild, threshold search, or 2024–2025 rerun was performed.

## Assessment
Generalization is classified from return, drawdown, exposure, right-tail concentration, ex-best20, deferred-loser risk, year consistency, and activation count. No threshold search or 2024-2025 rerun was performed.
