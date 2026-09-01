# A-share Tail-to-Open LightGBM V1 — Stage A

## CONCLUSION

`STAGE_A_COMPLETE_OUTCOME_BLIND`

The fixed lane uses 59 features available no later than 14:25, a single raw
one-minute entry bar ending 14:56, and the first later legal open. No forward
return, model fit, portfolio result, or post-2023 security row was read.

## CHRONOLOGY

- Development: `2018-04-02` through `2021-12-31`.
- Validation: `2022-01-04` through `2023-12-29`.
- Final locked OOS: `2024-01-02` through `2026-08-11`.
- Final OOS remains `LOCKED_UNREAD`; only calendar/schema metadata was inspected.

## EXECUTION

The signal is formed after the completed 14:25 bar. The order is represented
by the VWAP of the bar ending 14:56 and is unfilled when pinned at the upper
limit. Exit is the first later legal open under T+1, suspension, limit, lot,
and frozen QD-010 corporate-action handling. Canonical cost is 20 bps per side.

## MODELS AND DECISION

Ridge and exactly three preregistered LightGBM profiles are allowed. Top-10 is
fixed. Development walk-forward must pass before validation is opened; final
OOS requires every validation continuation gate and a separate committed freeze.

## RESOURCES

The mounted external volume has at least 3700 GiB free.
Stage B may scan and materialize only 2018-2023 yearly shards. No 2024-2026
feature or label shard may be created before Stage C authorization.
