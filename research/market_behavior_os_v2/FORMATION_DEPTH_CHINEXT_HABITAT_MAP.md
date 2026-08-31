# Formation-depth x CHINEXT V1 habitat map

Frozen before joining the supported formation-depth market state to CHINEXT V1
outcomes. This is an incremental strategy-habitat test using already-consumed
2018--2023 exploratory evidence. It cannot create a threshold, veto, exposure
rule, or canonical strategy modification.

## State and mechanism boundary

The only tested habitat coordinate is the supported MKT-BREAKOUT-ECON-001 role:

- absolute state: CHINEXT_BOARD/ALL_STATUS
  `breakout_formation_depth20`;
- causal sensitivity: its existing `pit_3y_pct` after the 504-observation warm-up;
- market meaning: mean proportional mapped-high excess over each crossing
  security's strictly prior 20-session mapped-high level;
- established response: higher state precedes worse broad constituent downside,
  not lower terminal return and not a transition/crossing effect.

No closing-rejection, participation, acceptance, diffusion, concentration,
stock/industry-divergence, trend interaction, or combined score is tested as a
habitat predictor. PIT 0.20/0.80 tails are fixed distribution diagnostics only;
they are not proposed strategy gates.

The habitat hypothesis is falsifiable: for the same frozen CHINEXT V1 process,
formation depth may alter opportunity formation, adverse holding path, failure,
realization, or right-tail conversion. The broad-market downside result does not
presume which, if any, transfers to stock setups.

## Clock and population

State date equals the V1 entry signal date and is available only at the completed
15:00 close. Every selected entry executes strictly later under the frozen V1
ledger. Daily opportunity rows include zero-event days. Evaluated-event rows use
the engine's already-fixed price-structure-qualified evaluation population.
Completed-cycle rows are the exact one-to-one selected admissions and actual exits
in HAB-CHX-001.

The samples remain separate:

- `DAILY_PROCESS`: opportunity counts, including zero days;
- `EVALUATED_EVENT`: candidate/admission conversion within the frozen V1 setup
  process;
- `COMPLETED_CYCLE`: opportunity, failure, realization, and right-tail outcomes.

Same-date comparison cannot identify a date-level market state because every event
on a date shares it. Dependence is therefore handled by signal-date clustering,
while incrementality uses minimum continuous controls. This limitation is explicit;
no unavailable setup score, size, industry, or liquidity proxy is invented.

## Fixed endpoints

| family | sample | endpoints |
|---|---|---|
| opportunity | daily | `evaluated_count`, `candidate_count` |
| opportunity | evaluated event | `admissible_candidate`; `selected_admission` among admissible candidates |
| opportunity | completed cycle | `mfe`, `opportunity20` |
| failure | completed cycle | `mae`, `false_breakout`, `severe_loss10`, `extreme_loss20` |
| realization | completed cycle | `round_trip_return`, `giveback_from_peak`, `conversion20` among opportunity20 cycles |
| right tail | completed cycle | `winner20`, `winner50` |

MFE/MAE are observable through the frozen actual exit and remain habitat outcomes,
not entry predictors. No CAGR, portfolio exposure, turnover, optimized holding
period, alternate exit, or counterfactual fill is computed.

## Incremental design

The primary state is the continuous absolute formation-depth value so all six raw
years retain one semantic. Every endpoint uses a rank-linear partial association
after exactly three already-frozen same-date market controls:

- CHINEXT index 60-session trend direction;
- CHINEXT discovery breadth;
- CHINEXT realized-volatility level.

There is no variable selection. The causal PIT coordinate is a mandatory 2020--
2023 sensitivity and must share the primary sign. Every bootstrap resamples signal
dates as clusters. Every temporal estimate reports both fixed blocks, eligible
years, and leave-one-year-out behavior.

For economic scale, regress the raw endpoint on ranked controls only, then compare
mean endpoint residual in causal-PIT high (`>=0.80`) versus low (`<=0.20`) states.
The fixed absolute residual gaps are:

- daily counts: at least 0.25 events/day;
- continuous percentage outcomes (`mfe`, `mae`, `round_trip_return`,
  `giveback_from_peak`): at least 0.05;
- binary probabilities: at least 0.10.

These are evidence gates, not future operating thresholds.

## Portability, uncertainty, and multiple testing

An endpoint passes only if all hold:

- absolute partial-rank rho has magnitude at least 0.10;
- deterministic 2,000-replicate signal-date cluster-bootstrap 90% interval excludes
  zero;
- both 2018--2020 and 2021--2023 block rhos share the full sign and each has
  magnitude at least 0.05;
- at least four eligible years (minimum 20 observations and nondegenerate endpoint)
  share the sign;
- every eligible leave-one-year-out estimate shares the sign;
- causal-PIT partial rho has the same sign and magnitude at least 0.05;
- the controlled PIT-tail residual gap reaches its fixed endpoint floor with the
  same sign;
- bootstrap sign p-values pass Benjamini--Hochberg q=0.10 within the preregistered
  endpoint family.

Insufficient/nondegenerate cells are reported, never pooled into another endpoint.
A family cannot be rescued by another outcome, threshold, state coordinate, or
calendar subset.

## Decision

`HABITAT_SUPPORTED` requires at least one primary event/cycle endpoint to pass.
Daily counts alone may establish opportunity-density association but cannot define
a stock-setup habitat. A passing endpoint opens mechanism interpretation only:
opportunity, adverse path, failure, realization, or right-tail. It still does not
authorize a rule.

If no direct endpoint passes, formation depth remains a valid broad market tail-
risk state but is `NO_CHINEXT_V1_HABITAT_TRANSFER` under this test. The next
frontier returns to market behavior without changing thresholds or searching a
different V1 subset. CY-011 remains locked in every case.
