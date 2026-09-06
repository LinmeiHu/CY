# High cross-sectional dispersion idiosyncratic-tail mother V28 — Stage A

`CLOSED_OUTCOME_BLIND_DATA_COVERAGE_GATE_FAILED`

V28 was frozen as a genuinely different continuation of the market-dispersion result: on a completed high stock-specific-dispersion Friday, select one liquid extreme up-shock and down-shock representative per PIT industry, with the shock measured relative to the current industry median. No security outcome was read.

The frozen build produced zero legal candidates. A result-blind stage audit located the exact boundary:

| Stage | Eligible dates / rows |
|---|---:|
| Security history eligible | 1,885 dates / 2,867,179 rows |
| PIT industries with at least 10 members | 1,885 dates / 95,328 industry rows |
| Above same-date median liquidity | 1,885 dates / 1,199,237 rows |
| At least 500 liquid stocks and 20 industries | 1,198 dates / 1,023,356 stock rows |
| Exactly 252 consecutive prior complete market observations | 0 dates |

The market panel had only 83–203 fully covered dates per year from 2013 through 2020, with gaps in every year. Consequently no row could satisfy `lag252_cal_idx == current_cal_idx - 252`. Removing that condition would silently normalize against irregular historical coverage and weaken the frozen PIT contract merely to create samples.

No chart, future payoff, direction choice or post-2020 cohort was opened. The exact V28 formulation is closed; changing the 500-stock floor, 20-industry floor, 252-session history, p80 state, Friday clock or decile tails would be an outcome-blind but definition-level rescue and is not performed in this experiment.

Frozen specification SHA-256: `907508790f8f46ff29c32ea0af3c98d87c84715c333967e27f77e260bbfba196`.

Frozen empty-candidate identity SHA-256: `e2db101075b4d4441b24a13d0cabfb67c1934ff710e465b3270ca36d0741b442`.
