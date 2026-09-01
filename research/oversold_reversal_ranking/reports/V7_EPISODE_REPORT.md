# A-Share Deep-Oversold Portfolio V7

## 1. EXECUTIVE CONCLUSION

V7 confirms that the deep-oversold phenomenon has a coherent cluster-episode structure, but it
does not establish a robustly investable portfolio under the frozen finite-capital constraints.

The episode portfolio materially improves full-sample gross arithmetic: ending NAV is `1.1612`
versus `1.0016` for V5 and `1.0196` for V6; maximum drawdown improves to `-33.92%` from
`-44.35%` and `-39.84%`. Episode high-intensity baskets average `+3.64%` executable forward
return. These are economically meaningful results.

They fail the preregistered stability and capital-realization gates. V7 underperforms the simple
V5 control in two of three broad periods, with the full-sample advantage dominated by
2021-2023. Only `54.70%` of high-intensity signals receive any capital and only `19.84%` receive
their full intended allocation. Cash or envelope exhaustion gives zero allocation to `8,993`
high-intensity signals, versus `2,878` zero-cash misses in V6. The portfolio's 59 episodes have a
`49.15%` win rate and negative median P&L; the top 10% of profitable episodes provide `52.87%`
of all positive episode P&L.

**Verdict: `EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE`.**

The deep-oversold capitalization lane is closed. No V8 rescue study is recommended.

## 2. ENVIRONMENT / COMMIT / VALIDATION

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `5219e5bf7b592be0c4b2fcf868e8779e71e64140`
- Starting status: clean
- Certified input hashes: all verified
- V5 control maximum difference: `0.0`
- V6 control maximum difference: `0.0`
- Primary basis: gross, zero transaction costs
- Result invariants: all zero
- Checkpoint: created only after artifacts, tests, and staged diff are validated

Validation covers causal `N_t` and `M_t`, same-date exclusion, warm-up, high-intensity state,
20-session inclusive episodes, nonoverlap, episode-start NAV, cumulative envelope, true cash,
no leverage, next-open entry, fixed lot holding, legal exits, NAV identity, and signal/lot
reconciliation.

## 3. FROZEN RESEARCH HISTORY

| Version | Verdict | Frozen conclusion |
|---|---|---|
| V1 | `DEPTH_ONLY` | Deep drawdown is the event carrier. |
| V2 | `RISK_FILTER_ONLY` | Reversal confirmation reduces risk, not return alpha. |
| V3 | `SIZING_SIGNAL_ONLY` | t0 state predicts falling-knife risk, but not a veto. |
| V4 | `SIZING_SURVIVES` | Risk sizing improves event arithmetic. |
| V5 | `EVENT_ALPHA_COLLAPSES` | Event alpha fails true finite-capital NAV translation. |
| V6 | `CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS` | Count intensity is real, but independent date budgets saturate. |

V7 does not modify V1-V6 evidence. The exact V5/V6 event stream contains `22,357` events across
`4,835` securities and `1,228` active entry dates, from signal date `2020-01-02` through
`2026-07-08`.

## 4. V7 HYPOTHESIS AND FROZEN CONTRACT

The single hypothesis is that consecutive high-intensity dates are manifestations of one market
stress episode, rather than independent opportunities, and should share a finite capital
envelope.

V7 reuses V6's causal entry-date intensity:

`I_t = N_t / M_t`

where `M_t` is the median positive signal count across strictly prior active dates. After the
unchanged 60-active-date warm-up, `I_t > 1` is high intensity. No top-quintile or fixed-count
trading threshold is used.

An episode starts on a high-intensity legal entry date and lasts exactly 20 market sessions,
including the first session. Its cumulative envelope is fixed at `100% * EpisodeStartNAV`.
Within the episode, only high-intensity dates may request:

`RawRequest_t = 5% * EpisodeStartNAV * I_t`

`EpisodeRequest_t = min(RawRequest_t, remaining envelope)`

`Deployed_t = min(EpisodeRequest_t, available cash)`

Only actual deployment consumes the envelope. Same-date stocks split capital equally. There is
no leverage, borrowing, forced sale, roll-forward, V3/V4 stock sizing, altered hold, or parameter
search.

## 5. CONTROL REPRODUCTION

| Metric | V5 expected | V5 reproduced | V6 expected | V6 reproduced |
|---|---:|---:|---:|---:|
| Ending NAV | 1.0016248465 | 1.0016248465 | 1.0195803469 | 1.0195803469 |
| CAGR | 0.0256% | 0.0256% | 0.3065% | 0.3065% |
| Volatility | 23.3198% | 23.3198% | 22.2584% | 22.2584% |
| Max drawdown | -44.3500% | -44.3500% | -39.8446% | -39.8446% |
| Average exposure | 76.7385% | 76.7385% | 70.7611% | 70.7611% |
| Trades | 22,357 | 22,357 | 19,479 | 19,479 |

Every reported difference is exactly zero.

## 6. EPISODE POPULATION

The causal rule identifies `59` nonoverlapping episodes. All `556` high-intensity dates and
`19,852` high-intensity signals belong to an episode. Another `2,505` low-intensity signals are
ineligible by the frozen architecture. Episodes contain `21,033` total signals on active dates
inside their 20-session lifecycles; remaining low-intensity dates occur outside an episode.

| Cross-episode statistic | Mean | Median | p90 | Maximum |
|---|---:|---:|---:|---:|
| High-intensity dates | 9.42 | 10 | 16 | 20 |
| Total qualifying events | 356.5 | 223 | 811.2 | 2,122 |
| Envelope utilization | 74.86% | 95.30% | 100.00% | 100.00%* |
| Cash-blocked fraction | 29.61% | 18.19% | 76.61% | 90.11% |

\*The machine maximum exceeds 1.0 only by `1e-15` floating-point noise; the invariant tolerance
confirms no envelope breach.

An episode averages 9.4 eligible high-intensity dates, demonstrating that the V6 date requests
are usually repeated observations of one continuing stress interval.

## 7. PER-EPISODE ECONOMICS

| Metric | Result |
|---|---:|
| Episodes | 59 |
| Profitable episodes | 29 |
| Win rate | 49.15% |
| Mean episode P&L | +0.2732% NAV units |
| Median episode P&L | -0.1341% NAV units |
| Mean episode gross return | +0.4421% |
| Mean high-intensity forward basket return | +3.6439% |
| Total episode P&L | +0.1612 NAV |
| Capital-weighted episode trade return | +0.3400% |

The gap between a `+3.64%` equal-event basket and `+0.34%` capital-weighted episode return is the
same hierarchy problem seen in V5/V6: finite cash does not reproduce event weights. Profitable
episodes generate `8.60x` final net gross P&L because losing episodes offset most positive P&L.

P&L is concentrated. The best episode supplies `14.05%` of positive episode P&L; the top five
supply `46.72%`; the top 10% of episodes supply `52.87%`. The largest episode contributor begins
`2025-03-31`, earns `+0.1949` NAV, and alone exceeds the strategy's full-period net gross profit.

Every episode's dates, NAV/cash at start, intensity, requests, deployment, blocking, utilization,
zero allocations, exposure, P&L, return, and drawdown are retained in the machine results.

## 8. CAPITAL SATURATION

| Diagnostic | V6 date budget | V7 episode budget |
|---|---:|---:|
| Raw/requested capital | 196.184 | 203.613 raw; 99.693 after envelope |
| Deployed capital | 56.249 | 47.413 |
| Cash-blocked capital | 139.934 | 52.280 |
| Cash-blocked share of capped request | 71.33% | 52.44% |
| Highest-intensity cash-blocked share | 87.39% | 77.85% |
| Zero allocations from cash | 2,878 | 7,028 |
| Zero allocations from envelope | n/a | 1,965 |

The episode cap makes cash-blocking accounting more coherent and lowers the blocked fraction by
18.89 percentage points. It does not solve realized access to the opportunity. Relative to raw
requests, `76.71%` remains undeployed overall and `92.95%` in the highest-intensity fifth. Only
`54.70%` of high-intensity signals receive any allocation, and only `19.84%` receive the full
intended amount. V7 enters `10,859` trades on `389` dates, compared with `19,479` trades in V6.

The 100% envelope therefore controls repeated requests but creates a second rationing channel.
This is not a defect to tune away: it is the economic implication of the frozen architecture.

## 9. CAPITAL TIMING WITHIN EPISODES

| Session | High dates | Signals | Requested | Deployed | Basket Ret20 |
|---:|---:|---:|---:|---:|---:|
| 1 | 59 | 1,471 | 10.165 | 6.868 | +0.08% |
| 2 | 33 | 1,340 | 7.322 | 3.383 | -0.10% |
| 3 | 31 | 757 | 7.320 | 3.291 | -0.27% |
| 4 | 27 | 1,006 | 6.948 | 2.619 | +0.19% |
| 5 | 23 | 716 | 6.214 | 2.096 | +2.78% |
| 6 | 26 | 1,261 | 6.420 | 2.440 | +3.00% |
| 7-12 | 159 | 6,890 | 34.0 | 12.97 | mixed, -0.43% to +1.39% |
| 13-16 | 103 | 2,434 | 14.64 | 8.86 | mixed, -0.60% to +1.42% |
| 17-20 | 95 | 3,977 | 6.71 | 4.88 | +0.61% to +2.40% |

Deployment is front-loaded by availability and envelope consumption, while stronger descriptive
basket returns often appear later. The table is diagnostic only; it does not authorize choosing
episode days or changing the lifecycle.

## 10. EVENT / DATE / CLUSTER / EPISODE BRIDGE

| Economic unit | Equal-weight executable forward result |
|---|---:|
| Stock event | +4.3191% |
| Active date | +0.2637% |
| V6 highest count-rank fifth | +1.8511% |
| V7 high-intensity episode | +3.6439% mean; +2.7430% median |

Episodes organize the statistical effect better than isolated dates: they recover much of the
event-level forward mean. Yet the actual finite-capital episode return is only `+0.3400%` per
deployed-capital unit and fewer than half of episodes are profitable. The true descriptive unit
is a stress episode, but it is not a stable investable unit under fixed cash and holding.

## 11. GROSS PORTFOLIO COMPARISON

| Metric | V5 Equal | V6 Count-Aware | V7 Episode |
|---|---:|---:|---:|
| Starting NAV | 1.0000 | 1.0000 | 1.0000 |
| Ending NAV | 1.0016 | 1.0196 | 1.1612 |
| Cumulative return | +0.16% | +1.96% | +16.12% |
| CAGR | +0.03% | +0.31% | +2.39% |
| Annualized volatility | 23.32% | 22.26% | 20.24% |
| Max drawdown | -44.35% | -39.84% | -33.92% |
| Sharpe-like | 0.118 | 0.125 | 0.218 |
| Calmar | 0.0006 | 0.0077 | 0.0704 |
| Average exposure | 76.74% | 70.76% | 55.93% |
| Median / max exposure | 84.76% / 100% | 85.00% / 100% | 63.95% / 100% |
| Average / minimum cash ratio | 23.26% / 0% | 29.24% / 0% | 44.07% / 0% |
| Annualized turnover | 19.34x | 17.74x | 14.02x |
| Trades | 22,357 | 19,479 | 10,859 |
| Actual entry dates | 1,228 | 1,228 | 389 |
| Average / max positions | 280 / 3,354 | 244 / 3,234 | 136 / 1,847 |
| Average largest position | 4.67% | 1.46% | 1.02% |
| Average top-5 concentration | 17.43% | 6.35% | 4.70% |

V7 gains `15.96` ending-NAV points over V5 and `14.16` over V6, lowers volatility by 3.08 and
2.02 percentage points, and improves max drawdown by 10.43 and 5.93 points. These improvements
are meaningful, not numerical noise. They are insufficient for survival because they fail the
cross-period requirement and come with much lower participation/exposure.

## 12. ANNUAL RESULTS

| Year | V5 | V6 | V7 |
|---|---:|---:|---:|
| 2020 | -1.40% | -2.65% | -1.46% |
| 2021 | +11.75% | +16.62% | +18.82% |
| 2022 | -19.47% | -16.90% | -12.05% |
| 2023 | +8.36% | +11.93% | +14.34% |
| 2024 | -9.72% | -13.08% | -16.20% |
| 2025 | +23.33% | +27.96% | +30.25% |
| 2026 partial | -6.43% | -13.19% | -9.64% |

V7 is better than V6 in every year except 2024 and improves the long V5 drawdown interval. It
still exhibits large alternating gains and losses and has only `2.39%` gross CAGR before any
costs.

## 13. BROAD-PERIOD STABILITY

| Block | Episodes | Events | Avg intensity | V5 gross | V6 gross | V7 gross | V7-V5 | V7-V6 | V7 maxDD | Cash blocked | Episode wins |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018-2020* | 8 | 1,670 | 4.54 | -1.40% | -2.65% | -1.46% | -0.06 pp | +1.18 pp | -11.03% | 61.98% | 37.50% |
| 2021-2023 | 29 | 8,548 | 4.26 | -2.48% | +8.47% | +19.48% | +21.97 pp | +11.01 pp | -30.53% | 48.74% | 55.17% |
| 2024-2026 | 22 | 10,815 | 9.76 | +4.18% | -3.45% | -1.37% | -5.55 pp | +2.08 pp | -33.92% | 52.91% | 45.45% |

\*The event cohort begins in 2020, so the first block contains only 2020 observations.

V7 improves on V6 in all three blocks, demonstrating that episode organization is better than
independent count-aware requests. It underperforms the simpler V5 control in two blocks. The
entire full-period gain relative to V5 comes from 2021-2023, while the latest and largest-event
block loses money and trails V5 materially. That fails the explicit survival standard.

## 14. DRAWDOWN AND RISK INTERPRETATION

During V5's largest `2020-07-14` to `2024-02-05` drawdown, V5 loses `-44.35%` and V7 loses
`-27.55%`. During V6's largest `2021-12-16` to `2024-02-05` drawdown, V6 loses `-39.84%` and V7
loses `-33.44%`. The full-sample V7 maximum drawdown remains severe at `-33.92%`.

Some improvement comes from architecture, but some is mechanical de-risking: V7 average exposure
is only `55.93%`, about 21 percentage points below V5, with fewer than half as many trades.
The gross CAGR and drawdown combination does not justify a standard-cost investability study.

## 15. ECONOMIC INTERPRETATION

The hierarchy is now resolved:

1. Deep drawdown creates a real stock-event mean-reversion effect.
2. Events cluster into market-stress episodes with stronger forward baskets.
3. Independent daily budgets misread repeated stress observations as fresh capital capacity.
4. A cumulative episode envelope improves portfolio placement and risk metrics.
5. Frozen 20-session holdings and finite cash still ration most high-intensity signals, while
   episode outcomes remain regime-dependent and concentrated.

Thus the descriptive economic unit is the cluster episode. Under the frozen real-execution and
finite-capital constraints, however, none of the event, date, count-budget, or episode units
produces sufficiently stable gross portfolio economics to justify further capitalization work.

## 16. EXACT VERDICT

`EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE`

Episode organization clearly explains the clustering structure and improves full-period gross
NAV, drawdown, and saturation accounting relative to V6. It does not pass cross-period robustness,
participation, P&L concentration, or economic investability standards. `EPISODE_PORTFOLIO_SURVIVES`
would require improvement over both controls across broad periods; V7 instead trails V5 in two
of three.

## 17. CAPITALIZATION-LANE CLOSURE

Close the deep-oversold capitalization lane and preserve V1-V7 as frozen evidence. Do not run
further architecture, threshold, leverage, holding-period, factor, technical-indicator, volume,
or machine-learning rescue tests.
