# I0 fixed3 baseline reaudit — running checkpoint

## Current verdict

The score-generation chain is reproducible by explicit `(t,j,symbol)` identity for both consumed years. No row misalignment, scale mismatch, seed binding error or score-cache shortcut has been observed in that layer. This does **not** yet certify the `+17.4396%` account return: the prior single-seed producer called `verify_a0(2020)`, which only re-read the archived fixed3 ledger and checked summary parity. A fresh fixed3 execution has not started because the independent all-stock attention session is actively using MPS and substantial memory.

## What the old reports actually did

- `I0_s17`, `I0_s29`, and `I0_s43` were independently executed in 2020 from a common fixed3 positive gate and common canonical start, with only the ranking score changed.
- `I0_FIXED3` was not independently re-executed by that script. It was returned by `verify_a0` from the authoritative archived ledger.
- The old rows are therefore a fixed-gate ranking comparison, not three fully independent strategy contracts.
- The synergy report reused the same archived fixed3 ledger and the single-seed ledgers.

## Keyed reconstruction

For 2020 (817,778 rows) and 2021 (930,284 rows), the keyed daily files, `KEYS.parquet`, and all three `I0_s*.npy` arrays agree exactly. The audit inputs now bind every `j` to the canonical panel `symbol`; missing or swapped mappings are rejected. Recomputing each seed's average-tie daily percentile, taking their fixed mean, and applying `mean(BRANCH_s17,s29,s43)>0` reproduces the stored consensus, gate, and authoritative account signal rows exactly. The account source sorts score descending and `j` ascending and scans beyond an unplannable high-ranked candidate until ten plans are made or candidates are exhausted.

## Stock PnL repair

The old diagnostic added the same BUY/SELL economic cashflow from both `lot_fills` and `cashflows`. The repaired calculation uses `lot_fills` for transactions and only non-BUY/SELL `cashflows` for dividends/tax/other stock events, plus start/end marked inventory and the account receivable/tax-reserve bridge. It reconciles exactly to NAV for archived fixed3 2020/2021 and all three archived 2020 single-seed accounts. Annual NAV and returns are unchanged. Any old profit-contribution ranking built from the duplicated formula must be regenerated; the fixed3 headline return is not invalidated by this attribution defect.

## Answers pending fresh execution

Fresh four-arm return parity, complete ledger parity, real-account triplicate-seed identity, and real-account shuffled-row invariance remain queued. No implementation parameter will be changed to match archived returns.

TASK_STATUS = RUNNING  
AUDIT_TARGET = CENTERED_TOP10_H10  
SOURCE_LINEAGE_COMPLETE = PARTIAL_ACCOUNT_EXECUTION_PENDING  
FIXED3_FRESH_REPLAY_EXECUTED = NO_RESOURCE_GATED  
OLD_I0_CACHE_SHORTCUT_USED_FOR_NEW_RESULT = NO  
FOUR_ARMS_COMMON_CONTRACT = DESIGNED_NOT_YET_EXECUTED  
KEYED_SCORE_PARITY = PASS_2020_2021_EXACT  
FIXED3_ARCHIVED_LEDGER_PARITY = PENDING_FRESH_REPLAY  
SINGLE_SEED_ARCHIVED_LEDGER_PARITY = PENDING_FRESH_REPLAY  
TRIPLICATE_SEED_ACCOUNT_IDENTITY = PENDING_FRESH_REPLAY  
STOCK_PNL_NAV_RECONCILIATION = PASS_EXACT_DECIMAL  
CONFIRMED_RESULT_AFFECTING_BUGS = NONE_CONFIRMED_YET  
DEFENSIVE_GAPS_NOT_TRIGGERED = OLD_NPY_KEY_BINDING_WAS_UNGUARDED_BUT_CURRENT_FILES_MATCH_EXACTLY  
TRAINING_MODIFIED = NO  
2022_CANDIDATE_RESULTS_COMPUTED = NO  
2023_RESULTS_OPENED = NO  
2024_2026_OPENED = NO  
PRODUCTION_APPROVED = NO  
LOCAL_COMMIT = db0160d6977a680ee4405b816d9b8b058de42d2e (initial audit checkpoint; current comparator patch pending commit)
AUDIT_REMOTE_SHA = PENDING  
REPORT_PATH = research/ashare_path_long_training_v1/account_diversification_v1/account_aligned_alpha_v1/i0_fixed3_baseline_reaudit_v1/FINAL_REPORT.md

REPRODUCIBILITY_VERDICT：分数链已复现；账户端到端仍未完成，不能把旧摘要/旧账本一致称为完整复现。

IMPLEMENTATION_CORRECTNESS_VERDICT：已确认股票 PnL 归因重复记账，但未改变 NAV；尚未确认影响历史收益的执行错误。

ENSEMBLE_EFFECT_VERDICT：旧账本上的描述性差值为 `0.1743961630908 - mean(-0.0212670093368,-0.0211164431040,0.0953723436544) = 0.1567331993529333`，但须等共同合同 fresh replay 后才能确认成立。

GENERALIZATION_VERDICT：本次没有新增独立样本，2021 也已被消费，不据此宣称未来有效。
