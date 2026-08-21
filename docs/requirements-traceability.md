# Requirements traceability

> 本文件保留为旧版简表。当前统一、带来源页码和状态边界的权威入口是 `docs/cyq_game_requirement_matrix.md`。

| Material requirement | Implementation | Acceptance evidence |
|---|---|---|
| PIT/available-at and no future data | `data/pit.py`, `PITMeta` | `test_pit.py` |
| Revision-aware fundamental PIT, missing/zero semantics | `data/pit.py`, `fundamentals.py` | `test_pit.py`, `test_fundamentals.py` |
| Audit/going-concern independent hard override | `fundamentals.py`, `backtest/engine.py` | `test_fundamentals.py`, `test_e2e.py` |
| Industry membership PIT and sector leave-one-out | `data/pit.py`, `backtest/engine.py` | `test_pit.py`, `test_states.py`, `test_e2e.py` |
| Log price grid, P01/P99, mass conservation | `chip/core.py` | `test_chip.py` |
| Uniform baseline and exact cohort replacement | `chip/core.py` | `test_chip.py` |
| Transaction/economic/latent ledgers | `chip/ledgers.py` | `test_ledgers.py` |
| CYQK pre/post, CYC/CYS/RPY, peaks/migration | `chip/features.py` | `test_features.py` |
| Six-phase market, tactical overlay, sector LOO | `state/classifier.py` | `test_states.py` |
| T0–T9 multi-label, score/reliability split | `state/classifier.py` | `test_states.py` |
| Risk state independent and overriding | `state/classifier.py`, game gate | `test_decision.py` |
| Participant hypotheses and alternatives | `game/decision.py` | `test_decision.py` |
| Complete EdgeCard or fail closed | `game/decision.py` | `test_decision.py` |
| Scenario probabilities and Q(action) costs | `game/decision.py` | `test_decision.py` |
| Observability independent from DQ | `game/decision.py` | `test_decision.py` |
| Fractional Kelly, capacity, reflexivity, caps | `portfolio/sizing.py` | `test_portfolio.py` |
| Versioned TradePlan and posterior add gate | `execution/plans.py` | `test_plans.py` |
| T+1, limits, suspension, partial/blocked fill | `execution/simulator.py` | `test_execution.py` |
| Append-only operator/holdout/experiment ledger | `data/pit.py`, `data/events.py` | `test_governance.py` |
| Walk-forward/holdout/cost/capacity backtest | `backtest/engine.py`, `backtest/diagnostics.py` | `test_e2e.py` |
| Independent robustness and ablation matrix | `backtest/robustness.py` | `test_e2e.py` |
| Idempotent deterministic replay | `data/events.py`, `cli.py` | `test_events.py` |
| Shadow reconciliation and durable kill switch | `execution/reconciliation.py`, `cli.py` | `test_e2e.py`, `test_account_reconciliation.py` |
| Live off by default | configuration validation | `test_config.py` |

Book thresholds are labeled `BOOK_PRIOR` in feature/state output and remain calibration candidates. Game modules are disabled from real positions by the production boundary; a module that fails out-of-sample ablation must remain disabled.
