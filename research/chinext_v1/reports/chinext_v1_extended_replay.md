# ChinNext V1 — preregistered 2018–2021 extended-history replay

> PREREGISTERED_EXTENDED_HISTORY_VALIDATION / BOUNDED PIT-B / NOT STRICT PIT-A

- STRATEGY_SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- REPLAY_SPEC_COMMIT: `c051b94c967d591d2b959290657e1ba8579b307f`
- FORMAL_REPLAY_EXECUTION_COUNT: `1`
- 2018_2021_SAMPLE_STATUS: `CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION`

## Frozen metrics

- TOTAL_RETURN: `64.822373%`
- MAX_DRAWDOWN: `-20.762679%`
- TRADES: `194`
- WIN_RATE: `45.360825%`
- MEDIAN_TRADE: `-0.970512%`
- MEAN_TRADE: `3.045568%`
- TOP20_PNL_CONCENTRATION: `73.517871%`
- RETURN_EX_BEST20: `-50.157289%`
- 2018_TOTAL_RETURN: `-3.783517%`
- 2019_TOTAL_RETURN: `23.490683%`
- 2020_TOTAL_RETURN: `5.267229%`
- 2021_TOTAL_RETURN: `31.776904%`

The replay reuses the frozen V1 signal, portfolio, next-open, T+1, limit, cost, and corporate-action semantics. Historical identity/state is overlaid from the exact CY-029 artifact; physical 302132.SZ source rows are mapped to canonical 300114.SZ from official data, and unresolved events remain fail-closed.
