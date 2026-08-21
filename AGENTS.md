# CYQ-GAME engineering invariants

筹码分布是带记忆和模型误差的持仓成本状态估计器，不是庄家账户透视器；T0–T9 是状态，不是订单；任何交易必须在大盘、板块、筹码迁移、收益来源、替代解释、尾部风险和真实可成交性共同成立后才有资格执行。

1. Never use data after `decision_at`; every record carries `available_at` and `snapshot_id`.
2. A signal formed on bar t cannot fill inside bar t; `CYQK_pre` uses the pre-trade chip state.
3. Chip mass and all ledgers conserve exactly; normalization must never hide a bug.
4. T0–T9 is multi-label; market cycle may be multi-class; risk is independent and overrides both.
5. Point-in-time sector membership and leave-one-out sector features are mandatory.
6. Unknown float, corporate action, trading status, or market rule makes `hard_valid=false` and blocks new risk.
7. Sizing probabilities are out-of-sample calibrated; HMM/state probabilities are filtered, never smoothed with future observations.
8. Experiments, failed trials, final-holdout access, overrides, and operator events are append-only.
9. State generation, orders, event replay, and reconciliation are idempotent.
10. Live broker access is disabled by default; account mismatch triggers the kill switch.
11. A release must support rollback of code/schema, pending orders, and portfolio state.
12. `pytest -q`, `ruff check .`, and `mypy src/` must pass.
13. A stock state is not an order; every trade requires a `StrategyFamily` and a complete `EdgeCard`.
14. Participant states are latent hypotheses, never claims about real accounts.
15. `NO_TRADE` is a first-class action and is evaluated against every active action.
16. `Q(action)` includes fees, slippage, market impact, reflexivity, and blocked-exit tail loss.
17. `DataQuality` and `Observability` are separate; high data quality cannot override ambiguity.
18. Kelly sizing uses only OOS-calibrated trade probabilities and is always fractional.
19. Adding risk requires posterior improvement and a higher protective stop; never average down merely because price fell.
20. Every `TradePlan` is versioned; a changed thesis creates a new plan.
21. Operator overrides, holdout access, and failed trials are append-only and auditable.
22. Probe trades must be bona fide orders; spoofing, wash trading, and signal manipulation are forbidden.
23. `configs/data_asset_registry.json` is the sole authoritative input allowlist; unregistered data cannot feed state, signals, sizing, execution, backtests, or performance claims.
24. New, changed, moved, re-downloaded, reinterpreted, or replacement data must be registered before use with source, path, coverage, units, PIT grade, `available_at`, `snapshot_id`, hashes, quality evidence, allowed uses, blocked uses, and activation gates; silent substitution is forbidden.
25. Registration is not activation: only `RESEARCH_CONDITIONAL` assets whose own and cross-table gates pass may feed research; strict outputs require all necessary inputs to be PIT grade A. `QA_ONLY`, `DISCOVERY_ONLY`, `DEMO_ONLY`, `GENERATED_OUTPUT`, and `UNAVAILABLE` assets are never research inputs.
26. A missing path, manifest/hash mismatch, unknown lineage, or missing join fails closed. Runtime databases, caches, derived files, reports, and other generated outputs never become source facts by discovery.
