# 复现命令

固定工作树与分支：`/Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1`，`research/five-strategy-scaling-regime-v1`。外部原始数据和父研究缓存按 input_manifest.json 绑定；Git 包含代码、契约、检查与压缩结果，不包含巨量原始行情。

```sh
cd /Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1
export PYTHONPATH=.:src
/opt/anaconda3/bin/python -c 'from research.scaling_regime_v1.audit import verify_inputs; verify_inputs()'
```

已绑定的执行输入可直接重放。以下入口检查已有 receipt；独立实际重放证据见 continuous_determinism.csv 与 root_capital_trace_receipts.json。不要删除封存缓存后悄悄重建成不同字节；在独立命名目录回放并比较原 receipt。准备输入源码为 snapshot.py、rebuild_inputs.py、quotes.py，其原始资格和 PIT 边界见报告。

```sh
/opt/anaconda3/bin/python -m research.scaling_regime_v1.signal_prefix
/opt/anaconda3/bin/python -m research.scaling_regime_v1.closure_checks
/opt/anaconda3/bin/python -m research.scaling_regime_v1.run_scaling
/opt/anaconda3/bin/python -m research.scaling_regime_v1.scaling_postcheck
/opt/anaconda3/bin/python -m research.scaling_regime_v1.mechanics_identity
/opt/anaconda3/bin/python -m research.scaling_regime_v1.determinism_v2
/opt/anaconda3/bin/python -m research.scaling_regime_v1.capital_trace
/opt/anaconda3/bin/python -m research.scaling_regime_v1.capital_trace_extra
```

实际账户的经济归因顺序如下。全部使用固定目标与原生退出。旧 audit.py、build_report.py、finalize.py 属于原始身份拒绝研究，不要用它们覆盖本次权威报告。

```sh
/opt/anaconda3/bin/python -m research.scaling_regime_v1.economics
/opt/anaconda3/bin/python -m research.scaling_regime_v1.fee_bridge
/opt/anaconda3/bin/python -m research.scaling_regime_v1.rebalance
/opt/anaconda3/bin/python -m research.scaling_regime_v1.states
/opt/anaconda3/bin/python -c 'from research.scaling_regime_v1.capital_state import run, portfolio_states; run(); portfolio_states()'
/opt/anaconda3/bin/python -m research.scaling_regime_v1.capacity
/opt/anaconda3/bin/python -m research.scaling_regime_v1.comparisons
/opt/anaconda3/bin/python -m research.scaling_regime_v1.drawdowns
/opt/anaconda3/bin/python -m research.scaling_regime_v1.state_details
/opt/anaconda3/bin/python -m research.scaling_regime_v1.state_samples
/opt/anaconda3/bin/python -m research.scaling_regime_v1.add_context
/opt/anaconda3/bin/python -m research.scaling_regime_v1.merge_final_details
/opt/anaconda3/bin/python -m research.scaling_regime_v1.report_v2
/opt/anaconda3/bin/python -m pytest -q tests research --junitxml=research/scaling_regime_v1/output/tests_v2.xml
FIVE_STRATEGY_INPUT_CONFIG=research/five_strategy_exit_risk_v1/input_config.json /opt/anaconda3/bin/python -m pytest -q tests/reproduction/test_mcb_external.py --basetemp=research/scaling_regime_v1/cache/pytest_registered_mcb --junitxml=research/scaling_regime_v1/output/registered_mcb_test.xml
/opt/anaconda3/bin/python -m research.scaling_regime_v1.finalize_v2
```

金额、股数、时间和原生会计均来自实际账户。日/分钟容量分母只是诊断，不改成交。逐笔输出较大，仓库中提供确定性 gzip；对应 CSV 在本机 output 下存在，可用 `gzip -dc 文件.csv.gz > 文件.csv` 恢复。若 gzip 超过 Git 单文件限制，按 `文件.csv.gz.part*` 的字典顺序拼接后解压；清单记录每份文件的 SHA256。

强制再次执行独立实际回放时，可先备份本任务的只读复核缓存；不要移动权威 `cache/accounts` 或父研究数据。示例：

```sh
REPLAY_BACKUP_TAG=$(date +%Y%m%d%H%M%S)
mv research/scaling_regime_v1/cache/capital_timeline_native research/scaling_regime_v1/cache/capital_timeline_native_saved_$REPLAY_BACKUP_TAG
mv research/scaling_regime_v1/cache/capital_timeline_scaling research/scaling_regime_v1/cache/capital_timeline_scaling_saved_$REPLAY_BACKUP_TAG
/opt/anaconda3/bin/python -m research.scaling_regime_v1.capital_trace
/opt/anaconda3/bin/python -m research.scaling_regime_v1.capital_trace_extra
/opt/anaconda3/bin/python -m research.scaling_regime_v1.determinism_v2
```

独立复核再次生成后，必须与权威账户每个核心文件逐字节一致；仅仅读取原有 receipt 的运行不计作新一次独立回放。
