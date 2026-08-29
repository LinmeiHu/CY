# ChinNext V1 exploratory smoke replay

> **CURRENT SURVIVOR UNIVERSE / NOT POINT-IN-TIME / SURVIVORSHIP BIASED / NOT VALID FOR FINAL PERFORMANCE CLAIMS**
>
> These are exploratory, survivor-biased, small-sample diagnostics. They are not
> an unbiased historical backtest and are not valid as final performance claims.

## Run identity

- RESEARCH_MODE: `EXPLORATORY_SURVIVOR_BIASED`
- SAMPLE_SYMBOLS:

```text
300001.SZ, 300027.SZ, 300055.SZ, 300082.SZ, 300111.SZ, 300139.SZ, 300165.SZ, 300192.SZ, 300220.SZ, 300245.SZ
300271.SZ, 300300.SZ, 300328.SZ, 300357.SZ, 300387.SZ, 300414.SZ, 300440.SZ, 300465.SZ, 300490.SZ, 300516.SZ
300543.SZ, 300569.SZ, 300595.SZ, 300620.SZ, 300647.SZ, 300671.SZ, 300696.SZ, 300723.SZ, 300752.SZ, 300779.SZ
300808.SZ, 300833.SZ, 300858.SZ, 300884.SZ, 300910.SZ, 300938.SZ, 300965.SZ, 300991.SZ, 301017.SZ, 301043.SZ
301071.SZ, 301099.SZ, 301127.SZ, 301161.SZ, 301192.SZ, 301222.SZ, 301266.SZ, 301302.SZ, 301345.SZ, 301439.SZ
```

- DATE_RANGE: `2024-01-02 .. 2025-12-31`
- RAW_UNIVERSE_COUNT: `1398` current survivors
- HISTORY_CANDIDATE_COUNT: `1225`
- RAW_SAMPLE_COUNT: `50`
- USABLE_SAMPLE_COUNT: `49`
- SAMPLE_SELECTION: current-survivor symbols with >=180 pre-start valid completed observations, sorted by symbol, then 50 deterministic equidistant indices; no return outcome used

Selection is based on pre-run history availability and symbol ordering only. No
post-run return or signal outcome is used. The replay runs only this sample, not
the full current-survivor universe.

## Data and market gate

- MARKET_GATE_ACTIVE: `YES`
- MARKET_GATE_REASON: exact QMT 399102.SZ daily history covers the full smoke range
- MARKET_ANCHOR: `399102.SZ` (QMT exact identity, no fallback)
- MARKET_INPUT_SHA256: `e096e4d50d0b6ac5062d4940bf0c17c0165dd1c44d5f49ce12d0e3754daa8779`
- EXECUTION_LIMIT_MODEL: `PARTIAL`
- RISK_WARNING_MODEL: known CY-006 is_st=true and current manifest ST names excluded by daily eligibility; complete historical risk-warning taxonomy is UNVERIFIED
- AVERAGE_HISTORY_VALID: `46.92` / day
- AVERAGE_LIQUIDITY_VALID: `26.56` / day
- AVERAGE_FINAL_ELIGIBLE: `26.56` / day

`PARTIAL` means CY-006's known daily trade status, exact open-limit block flags,
validity flags and missing/invalid opens are enforced, but the replay has no order
book/queue model. A blocked or invalid open is never silently filled. Historical
`is_st=true` is excluded, but the local evidence does not prove complete coverage
of every historical risk-warning subtype; this report does not claim it does.

## Signal diagnostics

- ENTRY_SIGNAL_COUNT: `43`
- MINVOL_PASS_COUNT: `37`
- BREAKOUT_VOLUME_SHADOW_PASS_COUNT: `31`
- BREAKOUT_VOLUME_MODE: `SHADOW` (logged, not an entry blocker)
- INDIVIDUAL_EXIT_SIGNAL_COUNT: `16`
- MARKET_EXIT_SIGNAL_DAYS: `191`
- SET_CHANGE_COUNT: `37`
- RANK_REPLACEMENT: `OFF`

Signals use completed close t only. B60, FULL40, MINVOL, breakout-volume and RS
windows are causal; orders first become eligible at a later session open.

## Trading and portfolio results

> **EXPLORATORY / SURVIVOR-BIASED / SMALL SAMPLE**

- ENTRY_BUY_EXECUTION_COUNT: `26`
- REBALANCE_BUY_LEG_COUNT: `34`
- BUY_FILL_COUNT: `60`
- SELL_FILL_COUNT: `54`
- COMPLETED_ROUND_TRIP_COUNT: `25`
- REBALANCE_SELL_LEG_COUNT: `29`
- WIN_RATE: `44.0000%`
- AVERAGE_TRADE_RETURN: `6.5870%`
- MEDIAN_TRADE_RETURN: `-1.3588%`
- TOTAL_RETURN: `19.6955%`
- ANNUALIZED_RETURN: `9.4867%`
- MAX_DRAWDOWN: `-6.1811%`
- AVERAGE_HOLDINGS: `1.109`
- MAX_HOLDINGS: `10`
- AVERAGE_INVESTED_RATIO: `11.2026%`
- TURNOVER: `5.5890x` (total traded notional / average NAV)
- T+1_BLOCKED_EXIT_COUNT: `5`
- T+1_EXECUTION_BLOCKED_COUNT: `0`
- FAILED_OPEN_EXECUTION_COUNT: `4`
- TRANSACTION_COST: `10.0` bps per side

Each desired member targets exactly 10%; with fewer than ten members the remainder
stays cash. Set-change-only prevents daily drift rebalancing. Failed executions
remain sticky pending. `acquisition_date` conservatively resets on any buy/top-up;
same-day exit signals are logged as `EXIT_SIGNAL_BLOCKED_BY_T1` and deferred.

## Corporate actions and audit trail

- CORPORATE_ACTIONS_APPLIED: `107`
- CORPORATE_ACTIONS_BLOCKED: `0`
- STALE_HELD_VALUATIONS: `0`
- EVENT_LEDGER: `research/chinext_v1/output/chinext_v1_smoke/event_ledger.jsonl` (`af92c6910c3fd3a30692cc4cdbce7db8ca06830c150dd0d4cb0dd3a3cefcc306`)
- EXECUTION_LEDGER: `research/chinext_v1/output/chinext_v1_smoke/execution_ledger.jsonl` (`ceba6ef4bb25cb5a45076404c0c1972f31200819c9ea078dab4f30ad9e30f577`)
- DAILY_NAV: `research/chinext_v1/output/chinext_v1_smoke/daily_nav.jsonl` (`eb4d49603594dde4baf3d59462899d33c364a79d82922fae3e7b32e57e5b9b85`)

Cash dividends and share multipliers use the repository's existing research replay
semantics. Past signal history is causally rebased into the post-action coordinate;
unmodeled blocking/rights actions affecting a held stock fail the run instead of
being normalized away.

## Limitations

1. The stock pool is today's survivor list projected backward. Delisted and former
   constituents are absent, so survivorship bias is structural and material.
2. The sample is only about 50 symbols; cross-sectional RS is therefore a sample RS,
   not a 1,398-stock or historical-PIT-universe RS.
3. Risk-warning coverage is incomplete, and current names are not treated as proof
   of historical state.
4. Daily open limit/tradability constraints are enforced, but there is no intraday
   queue, market-impact, or broker-level lot/sellability ledger.
5. Transaction costs are a fixed 10 bps per side; taxes, impact and borrow are not
   separately modeled. Unclosed positions remain marked at their last causal close.

The result is suitable only for deciding whether a stricter Phase 2 study is worth
doing. No parameter was optimized in this run.
