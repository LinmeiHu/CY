# Action-safe T+1 entry-gap attribution

EXP-EGP-001 tests whether a stock-specific signal-close-to-T+1-open gap contributes to the supported false-breakout topology. It does not test a gap filter or alternate fill.

## Execution and coordinate audit

- Completed cycles / exact fills / hard-valid signal+execution bars: `399` / `399` / `399`.
- Invalid coordinate steps / execution-open mismatches / nonzero intraday fill premiums: `0` / `0` / `0`.
- Action-event cycles / index-covered cycles: `1` / `399`.
- Every completed entry fills exactly at the T+1 session open. The varying feature is therefore the action-safe overnight gap relative to 399102, not execution slippage.

## Preregistered primary

| Raw rho | Within-year | LOYO + | Controlled rho | LOYO + | Duration/exit rho | Topology rho | Stock-gap neighbor rho |
|---:|---:|---:|---:|---:|---:|---:|---:|
| -0.072 | -0.084 | 0/8 | -0.079 | 0/8 | -0.056 | -0.061 | -0.099 |

## Frozen gates

- Raw / controlled / topology / neighbor / falsification: `FAIL` / `FAIL` / `FAIL` / `FAIL` / `FAIL`.

## Scientific decision

`REJECT` / `ENTRY_GAP_DOES_NOT_EXPLAIN_FALSE_BREAKOUT_TOPOLOGY`.

A surviving relationship would be entry-timing attribution, not evidence that a gap filter improves V1. No counterfactual fill, ranking, or portfolio replay is present.

## Strategy candidate

None. No entry, exit, filter, sizing, ranking, or production change was tested or authorized.
