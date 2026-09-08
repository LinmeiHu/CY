# SMV6 post-2023 execution chain

ENTRYPOINT: `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1/tools/build_smv6_rollforward.py` (`build_smv6_rollforward.py`) loads the registered historical QMT panel and `qmt_delta`, then calls `smv6._run_callbacks` through `IntentPlatform`.

CALL GRAPH:

`build_smv6_rollforward.load` → `IntentPlatform(...)` → `smv6._run_callbacks` → `smv6.frozen_namespace` callbacks → `IntentPlatform.order_target_percent` → `platform.intents` / local event stream.

INPUT FILES: `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1/qmt_delta/daily`, `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1/qmt_delta/minute_critical`, `/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2/smv6/availability.parquet`, and the historical source rooted at `/Users/linmei/Documents/CY-supermind-v6/research/supermind_v6/data`.

STATE FILES: callback context (`prev_trade_date`, pending membership/close state), platform positions, and the continuous calendar beginning 2018-01-01. The replay is one continuous run; it is not initialized at 2024.

OUTPUT FILES: `/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2/smv6/continuous_events.parquet`, `/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2/smv6/continuous_nav.parquet`, and this audit's `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1/research/capital_admission_v1/output/smv6_post2023_replay_intents.parquet`.

The previous `smv6_baseline.py` `< 2024-01-01` predicate is classified as a bounded legacy artifact export boundary. It is not the producer used by the authoritative post-2023 account.
