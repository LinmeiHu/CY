# Code Audit Handoff

Generated: `2026-09-19T09:49:28.267540+08:00`

## Repository

- Repo path: `/Users/linmei/Documents/CY-worktrees/minute-ret5-multiscale-autonomous-v2`
- GitHub remote: `https://github.com/LinmeiHu/CY.git`
- Branch: `codex/minute-ret5-multiscale-autonomous-v2`
- Previous HEAD: `2d6865f25324d5d2d6ac8532d4238af4e2693ed4`
- Implementation snapshot commit: `b207cda482355e7189efbccaebc27888cf833fd9`
- New snapshot commit created: **YES**
- Snapshot method: selective add only; no checkout, reset, source edit, formatting, or refactor.

## Running experiment

- PID: `79238`
- PID live at handoff capture: **YES**
- Stage: `P2_INNER_TRAIN`
- Arm: `RELATION`
- LR: `3e-06`
- Step: `25088/32000`
- Seed: `17`
- Year: `2020`
- RUN_STATE updated_at: `2026-09-19T09:46:50.026559+08:00`
- Command: `python research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/run.py inner-grid`
- Process cwd: `/Users/linmei/Documents/CY-worktrees/minute-ret5-multiscale-autonomous-v2`

## Code identity

`RUNNING_CODE_MATCHES_PUSHED_SNAPSHOT = YES`

Evidence:

1. The running command and cwd resolve to the committed experiment `run.py`.
2. `run.py` SHA256 is `571d3e89fbccb603f8053d6c3ed566f07884e75d50a28c55e1dcd7efda48901b`.
3. `TRAINING_SOURCE_INNER_FROZEN.py` has the identical SHA256 and was frozen immediately before process launch.
4. Every source hash recorded by `EXPERIMENT_SPEC.json` was rechecked before commit and matched its current runtime file.
5. External files loaded from the champion worktree were copied byte-for-byte under `audit_source_snapshot/champion/` and indexed by `SOURCE_IDENTITY_MANIFEST.json`.
6. No source used by the running process was edited during this audit.

This statement covers the running inner process. Formal evaluation has not started; its current frozen source and direct evaluator/account dependencies were also committed for future audit.

## Working tree

- State after implementation snapshot: **DIRTY** because the worktree contains substantial pre-existing unrelated research changes and live runtime state.
- Full status at capture: `CODE_AUDIT_WORKTREE_STATUS.txt`.
- Files included in implementation snapshot: 32 selectively staged source/config/evidence files; see commit `b207cda482355e7189efbccaebc27888cf833fd9`.
- Current-experiment source files left uncommitted: **NONE KNOWN**.
- Current-experiment dynamic files intentionally left uncommitted: live `RUN_STATE.json`, PID lock, logs, `__pycache__`, external checkpoints/caches/predictions.
- Other modified/untracked files are pre-existing research from unrelated lanes and were deliberately excluded.

## Relevant files for independent audit

1. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/run.py` — CONTROL/RELATION model, exact all-stock attention, self-mask, chunking, sampler, loss, LR/step grid, checkpoint/resume, inner evaluator.
2. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/formal.py` — forward inference, uniform-pool diagnostic, fixed3, signal gate, account bridge and holdout guard.
3. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/EXPERIMENT_SPEC.json` — frozen LR/step/seed/boundary/holdout contract and source hashes.
4. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/SOURCE_IDENTITY_MANIFEST.json` — exact runtime-to-audit source mapping and SHA256 values.
5. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/ATTENTION_IDENTITY_TEST.json` — zero-init, chunk parity, universe, masking, leakage and A0 account evidence.
6. `research/ashare_path_long_training_v1/train.py` — authoritative I0/O2 data batching, model wrapper and target/account feature semantics.
7. `research/ashare_wave_adaptive_path_v3/model.py` — underlying temporal encoder and stock representation implementation.
8. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/training_root_cause_v2/full_date_cross_stock_reconciliation_v1/evaluator.py` — keyed daily RankIC, Top10/Top50, lift and robustness evaluation.
9. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/training_root_cause_v2/master_alpha158_profit_first_v2/profit_pipeline.py` — authoritative annual RMB1m account adapter and profitability gate.
10. `research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/training_root_cause_v2/broader_ranking_portfolio_v1/run.py` — H10 execution/account engine bridge, costs, T+1, liquidity and capacity rules.

Additional byte-for-byte external sources are under:
`research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1/audit_source_snapshot/champion/`.

## Identity evidence retained

- Zero-init RELATION prediction difference: `0.0`
- Zero-init RELATION embedding difference: `0.0`
- Chunked vs unchunked maximum absolute difference: `5.587935447692871e-09`
- Complete same-date universe: `true`
- Self-attention masked: `true`
- Future labels used for context: `false`
- Authoritative 2020 A0 account reproduction: `PASS_EXACT_REPRODUCTION_OF_AUTHORITATIVE_A0`

## Large artifacts intentionally excluded

- `/Volumes/quant/.../training/INNER/**/step*.pt` checkpoints and resume state
- Alpha158/full-forward feature caches and raw market arrays
- embeddings and prediction parquet files
- account ledgers, NAV/order parquet files and snapshots
- process logs, PID locks and Python bytecode
- minute data and all other large research outputs

## Safety

- Current training was not stopped.
- Current training was not paused or restarted.
- No competing MPS process was started.
- No experiment logic was modified.
- No bug fix was applied.
- No selection rule, LR, step, seed, architecture, account rule or boundary rule was changed.
- No branch checkout occurred in the running worktree.

## Audit observations

No specific implementation bug was established during snapshotting. `NO FIX APPLIED`.
