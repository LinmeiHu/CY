# Architecture and safety boundary

## Direction of information

The system has a strict one-way boundary: raw/PIT facts create a chip-cost estimate; state models interpret that estimate; the game layer creates falsifiable hypotheses; portfolio and execution layers can only reduce or reject proposed risk. Interpretation can never rewrite source bars, corporate actions, free float, or chip snapshots.

| Layer | Produces | Must not do |
|---|---|---|
| PIT/data | as-of bars, rules, actions, memberships, filings | expose a future revision |
| Chip | uniform/cohort distributions, features, peaks | claim account ownership |
| State | market/sector/T0–T9 labels, independent risk | emit an order |
| Game | participants, EdgeCard, scenarios, action Q | omit `NO_TRADE` |
| Portfolio | fractional size under all caps | use in-sample probability |
| Execution | next-bar simulated fills, T+1 inventory | fabricate fills at limits/suspension |
| Governance | append-only plans/events/replay | delete failed evidence |

## Production boundary

`research`, `paper`, and `shadow` are supported. A config with `live_trading_enabled: true` is rejected. To cross that boundary, an organization must add a reviewed broker adapter, current dated MarketRules, dual approval, account reconciliation, kill switch, rollback rehearsal, and a separate release gate. No external model or vendor algorithm is assumed.

## Determinism

Every run has a stable `run_id`, configuration hash, source snapshot IDs, seed, ordered event sequence, and output digest. Replay verifies the digest. SQLite rows use PIT metadata, while decisions and operator activity are written as append-only JSONL envelopes with a hash chain.

Industry membership is resolved at the decision timestamp and sector features exclude the target symbol. Fundamental observations are selected by economic period, effective date, disclosure timestamp, and revision precedence. Missing fields retain explicit coverage loss rather than becoming zero; actual zero remains evidence. Audit or going-concern risk is an independent hard-risk override, while the remaining fundamental state influences participant ecology and strategy routing without rewriting the chip state.

Backtests use purged walk-forward folds and a separately locked final holdout. Robustness runs independently rebuild seven declared variants covering chip-engine choice, turnover replacement, sector evidence, and fractional-Kelly sizing. Each base run separately publishes cost-stress, realized-capacity, and gate-attribution diagnostics. Shadow reconciliation accepts a read-only external account snapshot and persists a kill switch on any cash, position, freshness, or digest mismatch.

See `requirements-traceability.md` for coverage and `operator-runbook.md` for execution.
