# ChinNext V1 — Gate D full PIT input validation

> Full bounded input/materialization correctness only. No strategy signal, trade, NAV, or performance was generated.

- GATE_D: `PASS`
- GATE_D_REPAIR_COUNT: `3`
- SPEC_SHA256: `dd1c9e3747a52138b1238c90f6c34d37a405f45cda6adc01a3264f286bdd5342`
- SPEC_COMMIT: `72dc09182bee897bde8b1b61a62b66d076f9f486`
- STRATEGY_INPUT_REQUIREMENT_MATRIX_STATUS: `PASS`
- SAFE_TO_RUN_EXTENDED_HISTORY_STRATEGY_REPLAY: `YES`
- STRICT_PIT_A: `NO`

## Full-scope metrics

- ALIAS_NORMALIZATIONS_APPLIED: `1`
- AUTHORIZED_FOUNDATION_HISTORICAL_SYMBOLS: `1098`
- AUTHORIZATION_FAILURE_COUNT: `0`
- CALENDAR_MISMATCH_COUNT: `0`
- CORPORATE_ACTION_FAILURE_COUNT: `0`
- DELISTINGS_CAPTURED: `7`
- DETERMINISM_MISMATCH_COUNT: `0`
- HASH_FAILURE_COUNT: `0`
- HISTORICAL_GEM_SYMBOLS_EVER_SEEN: `1097`
- HISTORICAL_SYMBOLS_EVER_SEEN: `1097`
- NEW_LISTINGS_CAPTURED: `387`
- NON_SURVIVORS_RETAINED: `39`
- PRICE_INPUT_MISSING_COUNT: `0`
- REQUIRED_STATE_MISSING_COUNT: `0`
- RISK_WARNING_REMOVALS_CAPTURED_VALIDATION_ONLY: `1`
- STAR_ST_INTERVALS_CAPTURED: `12`
- STATE_CONFLICT_COUNT: `0`
- STATE_UNKNOWN_COUNT: `0`
- ST_INTERVALS_CAPTURED: `12`
- SUSPENSION_SESSIONS_CAPTURED: `9594`
- TARGET_DAILY_STATE_ROWS: `803907`
- TRADING_DATES_VALIDATED: `973`
- UNIVERSE_MISMATCH_COUNT: `0`

## Deterministic logical materialization

- TARGET_ROWS: `803907`
- TARGET_SHA256: `22ee88047b14f905de8cb7e62bf6db4d029841695b973b55e3cf2c93ab5bfc7e`
- WARMUP_ROWS: `120642`
- WARMUP_SHA256: `6c092924063b5cc24b554cbc32e756cf178b27e53c3cc3f0061c50949f641115`
- COMBINED_SHA256: `d8cdf0c43b978e65dd019acf9df51b9e59e4f64f30d40e939da8923718f9c785`
- DETERMINISTIC: `PASS_LOGICAL_HASH_IDENTICAL`
- PERSISTENT_DUPLICATE_DAILY_STORE: `NO`

## Strategy input requirement matrix

| Strategy input | Source/authorization | Lookback | Earliest | Coverage | Fail closed |
|---|---|---|---|---|---|
| raw unadjusted close history | QD-001/CY-006 bounded PIT-B completed-bar facts | 180 completed observations; direct signal maximum 121 | 2017-04-12 | PASS | PASS |
| raw volume history | QD-001/CY-006 bounded PIT-B completed-bar facts | 31 observations for MINVOL; 21 for shadow breakout volume | 2017-04-12 | PASS | PASS |
| raw amount | QD-001/CY-006 bounded PIT-B completed-bar facts | 20 sessions | 2017-04-12 | PASS | PASS |
| historical GEM identity and listed trading age | CY-029 exact artifact | 180 listed completed sessions | 2017-04-12 | PASS | PASS |
| NORMAL/ST/STAR_ST state | CY-029 official-event-bounded subtype | daily effective state | 2017-04-12 | PASS | PASS |
| full-session suspension | CY-029 full-session daily only | daily state | 2017-04-12 | PASS | PASS |
| corporate-action event terms and causal coordinates | QD-010/CY-006 bounded PIT-B | all events affecting retained history | 2017-04-12 | PASS | PASS |
| next-session open, T+1, tradability, and open-limit state | CY-006 bounded PIT-B | execution session | 2018-01-02 | PASS | PASS |
| trading calendar | QD-003 exact calendar hash | entire warmup and replay range | 2017-04-12 | PASS | PASS |
| 399102.SZ market close | frozen 399102.SZ artifact | 21 sessions | 2017-12-01 | PASS | PASS |
| transaction cost and portfolio sizing | frozen strategy constant | 10 bps per filled side; 10 positions at 10% each | 2018-01-02 | PASS | PASS |

Explicitly unsupported rights participation remains fail-closed. The historical-state alias overlay is data-driven and only normalizes the official 302132.SZ physical projection to 300114.SZ inside the bounded pre-2025 interval.
