# A-Share Deep-Oversold Research Closure

## 1. Executive conclusion

The A-share deep-oversold research family is complete. It identified a genuine causal event-level
mean-reversion phenomenon, explained its risk and clustering structure, and rejected it as a
robust standalone finite-capital strategy under the frozen execution assumptions.

This is a scientific closure, not a failed study. The research separated a real statistical
effect from an investable portfolio claim and found that the latter does not survive strongly
enough.

```text
RESEARCH_FAMILY: A-SHARE DEEP OVERSOLD
ALPHA_DISCOVERY_STATUS: CLOSED
PORTFOLIO_CAPITALIZATION_STATUS: CLOSED
FINAL_PORTFOLIO_VERDICT: EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE
NO_V8: TRUE
RESCUE_TESTS_ALLOWED: NO
```

## 2. Repository / branch / authoritative endpoint

- Repository: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Authoritative completed V7 endpoint: `a698067f9f3d0600e1336e6b7065f12d657d3497`
- V7 verdict: `EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE`
- Closure basis: frozen V1-V7 reports, methodologies, implementations, and machine results

No V1-V7 artifact was altered to create this record.

## 3. Original hypothesis

The research began with “地量见地价”: volume exhaustion marks a bottom. That hypothesis is
closed and rejected. Volume Exhaustion V1 found that binary low volume did not supply the edge;
oversold mean reversion remained. Volume Exhaustion V2 found that continuous dry-up did not add
credible information inside comparable LOW observations.

Volume is not a surviving carrier. Alternative volume thresholds, shrinking-volume bottoms,
double-bottom volume confirmation, and MA/RSI/MACD rescue variants are permanently closed.

Authoritative predecessor evidence:

- [Volume Exhaustion V1](../../volume_exhaustion_bottom/reports/REPORT.md)
- [Volume Exhaustion V2](../../volume_exhaustion_bottom/reports/V2_REPORT.md)

## 4. V1-V7 research timeline

| Stage | Commit | Verdict | Authoritative conclusion |
|---|---|---|---|
| V1 | `bdd2c58d66dea7c4a5245031fd5a6002ccc2a047` | `DEPTH_ONLY` | Deep drawdown is the event-level carrier; crash speed, market, and industry attribution fail matched incrementality. |
| V2 | `7fad7e716a051f96abb75c278d3f35b5195b4175` | `RISK_FILTER_ONLY` | Reversal confirmation lowers downside but does not add return alpha and forfeits V-shaped rebound. |
| V3 | `98b7a383f4f51f2f84093e2ff41bfeef9d21d0b0` | `SIZING_SIGNAL_ONLY` | Falling-knife risk is causally observable, but risky events retain positive expectation and cannot support a hard veto. |
| V4 | `29906643e7ea9c0426d3c4ca7faf23e94fbd02d8` | `SIZING_SURVIVES` | Risk-aware sizing improves event-weighted arithmetic, not yet a finite-capital NAV portfolio. |
| V5 | `0850fbc8cc3bdcdb0fdd5acc1abe23117084185b` | `EVENT_ALPHA_COLLAPSES` | Executable event alpha survives, but calendar weighting and true overlapping capital reduce gross NAV to approximately flat. |
| V6 | `5219e5bf7b592be0c4b2fcf868e8779e71e64140` | `CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS` | Count intensity is informative, but independent date-level capital requests saturate and lack stability. |
| V7 | `a698067f9f3d0600e1336e6b7065f12d657d3497` | `EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE` | Episodes organize the phenomenon coherently but remain regime-dependent, concentrated, and severely capital-rationed. |

Compact evidence ladder:

- V1 deepest-quintile Ret20 was approximately `+3.67%` mean and `+1.68%` median, versus
  `+0.79%` and approximately zero in the shallowest; matched incremental crash-speed, market,
  and industry returns were `-0.62%`, `-0.08%`, and `-0.13%`.
- V2 immediate entry returned approximately `+4.41%` versus `+3.86%` after reversal waiting;
  waiting improved mean MAE from `-10.83%` to `-7.36%` but forfeited `+3.67%` pre-entry MFE.
- V3 Q5-Q1 severe-MAE incidence widened `+7.84` percentage points and no-trigger incidence
  widened `+8.75` points, but top-20% risk captured only `21.72%` of severe events.
- V4 risk sizing increased event Ret20 from `4.37%` to `4.64%` and return/downside efficiency
  by `6.81%`; this remained independent event arithmetic rather than portfolio NAV.

The authoritative reports are [V1](REPORT.md), [V2](V2_TIMING_REPORT.md),
[V3](V3_RISK_REPORT.md), [V4](V4_SIZING_REPORT.md), [V5](V5_PORTFOLIO_REPORT.md),
[V6](V6_CLUSTER_REPORT.md), and [V7](V7_EPISODE_REPORT.md).

## 5. Surviving scientific findings

1. Deep drawdown predicts subsequent A-share mean reversion at the event level.
2. The event effect survives causal executable-price translation.
3. t0 price state contains real falling-knife and future-MAE information.
4. High cross-sectional deep-oversold intensity is associated with stronger future baskets.
5. The phenomenon is naturally organized as clustered market-stress episodes rather than
   independent stock observations.

These findings remain reusable research knowledge. They do not constitute a currently
investable standalone strategy.

## 6. Rejected hypotheses

The following did not survive their required evidence standard:

- volume exhaustion as an incremental bottom signal;
- crash speed, market attribution, or industry attribution as incremental stock selectors;
- right-side reversal confirmation as a return-enhancing timing rule;
- hard veto from the V3 falling-knife score;
- V3/V4 risk sizing as portfolio-level value;
- constant 5% daily capital translation;
- count-aware date-by-date capital scaling; and
- episode-level finite-capital architecture as a robust standalone portfolio.

## 7. Event -> date -> portfolio -> cluster -> episode bridge

| Level | Frozen result | Meaning |
|---|---:|---|
| Executable stock event | mean Ret20 `+4.32%` | The causal event effect is real. |
| Equal-weight active date | mean basket `+0.26%` | Repeated events collapse when dates receive equal weight. |
| V5 Equal Gross portfolio | ending NAV `1.0016` | True capital competition removes nearly all gross edge. |
| V6 highest count fifth | basket `+1.85%` | Cluster intensity explains event-return concentration. |
| V6 Count-Aware Gross | ending NAV `1.0196`; 71.33% blocked | Independent daily requests cannot fund the cluster. |
| V7 high-intensity episode | mean basket `+3.64%` | Episode organization recovers descriptive opportunity. |
| V7 Episode Gross | NAV `1.1612`; CAGR `2.39%`; maxDD `-33.92%` | Full-sample arithmetic improves, but investability still fails. |

V7 beat V6 in all three broad periods but trailed the simpler V5 control in two of three. Only
54.70% of high-intensity signals received capital, episode win rate was 49.15%, median episode
P&L was negative, and the top 10% of profitable episodes supplied 52.87% of positive episode P&L.

## 8. Why event alpha failed portfolio capitalization

Event observations are not independent capital opportunities. Most occur simultaneously or on
consecutive dates within a small number of stress episodes. Event-weighted averages implicitly
give those episodes repeated capital, while a real portfolio has finite cash locked in overlapping
20-session positions.

Moving from events to dates therefore dilutes the mean. Scaling dates by count correctly locates
opportunity but requests capital when existing lots have already consumed cash. Grouping dates
into 20-session envelopes is more coherent, yet it rations most high-intensity signals and leaves
returns dependent on a small right tail of favorable episodes. Costs worsen an already weak gross
portfolio; they are not the root cause.

The central result is:

`EVENT ALPHA != PORTFOLIO ALPHA`

## 9. Final investability judgment

Deep oversold mean reversion is a genuine A-share statistical phenomenon, but it is not a robust
standalone finite-capital strategy under the frozen causal execution assumptions.

Much of the apparent event-level edge is amplified by repeated cross-sectional observations
inside clustered market-stress episodes. Cluster and episode analysis confirms that the structure
is economically real, but portfolio performance remains regime-dependent, right-tail
concentrated, capital-constrained, and too weak relative to drawdown and implementation costs.

The correct conclusion is: a real phenomenon was identified, decomposed, and rejected as a
standalone capitalizable strategy.

## 10. Closed research directions

```text
CAPITALIZATION_LANE: CLOSED
FINAL_VERDICT: EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE
NO_V8: TRUE
PARAMETER_RESCUE: PROHIBITED
LEVERAGE_RESCUE: PROHIBITED
HOLDING_PERIOD_RESCUE: PROHIBITED
THRESHOLD_RESCUE: PROHIBITED
NEW_FACTOR_RESCUE: PROHIBITED
ML_RESCUE: PROHIBITED
```

Do not reopen this lane with `-25%/-35%/-40%` drawdowns, 5/10/15/30-day holds, count thresholds,
episode lengths, top-N selection, leverage, volume filters, MA/RSI/MACD, V3-plus-episode
combinations, or ML classification of successful episodes. Any future use of such elements would
require a genuinely independent hypothesis and research design, not continuation of V1-V7.

## 11. Reusable evidence

Future independent work may reuse, without reopening failed conclusions:

- the causal deep-drawdown event stream;
- the V3 falling-knife score as a research feature;
- cluster-intensity measurement;
- causal episode construction;
- the portfolio accounting and corporate-action-safe execution infrastructure; and
- the V5/V6/V7 event-to-NAV reconciliation methodology.

The next research program should begin from a genuinely independent economic hypothesis rather
than another oversold rescue. This closure selects no new strategy.

## 12. Final authoritative status

```text
RESEARCH_FAMILY: A-SHARE DEEP OVERSOLD
ALPHA_DISCOVERY_STATUS: CLOSED
PORTFOLIO_CAPITALIZATION_STATUS: CLOSED
CAPITALIZATION_LANE: CLOSED
FINAL_PORTFOLIO_VERDICT: EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE
NO_V8: TRUE
RESCUE_TESTS_ALLOWED: NO
EVIDENCE_STATUS: FROZEN
```

This document and the accompanying closure manifest are the concise handoff authority. Numerical
details remain governed by the referenced V1-V7 reports and machine-readable results.
