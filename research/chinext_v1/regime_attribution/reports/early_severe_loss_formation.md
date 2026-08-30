# Early severe-loss formation

EXP-SLF-001 tests whether stock-specific adverse return is already visible by the third held session. It is path attribution, not a stop or exit experiment.

## Integrity and timing

- All cycles/severe losses: `399` / `44`.
- Day-3 survivors/severe/control-complete: `356` / `42` / `342`.
- Early exits before Day 3/severe: `43` / `2`; they remain in the Day-2 neighbor.
- Action-safe path rows/action cycles/Day-5 reconstruction error: `1744` / `5` / `2.55e-16`.
- AVAILABLE_AT_TIMESTAMP: `DAY3_SESSION_15:30_ASIA_SHANGHAI`.
- POTENTIAL_ACTION_TIMESTAMP: `NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION`.

## Frozen tests

| Test | Estimate | LOYO + |
|---|---:|---:|
| Day-3 stock-specific adverse raw | 0.321 | 8/8 |
| Day-3 controlled | 0.337 | 8/8 |
| Day-3 beta-adjusted neighbor | 0.320 | 8/8 |
| Day-2 all-cycle neighbor | 0.235 | 8/8 |
| Day-5 survivor neighbor | 0.340 | 8/8 |

Gates raw/control/neighbor/temporal/falsification: `True` / `True` / `True` / `True` / `True`.

## Decision

`DEEPEN` / `SEVERE_LOSS_PATH_SEPARATES_BY_DAY3_WITH_QUALIFICATION`.

No entry, stop, holding, exit, ranking, sizing, replay, or production modification was tested or authorized.
