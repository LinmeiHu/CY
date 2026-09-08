# 复现顺序

工作目录固定为 `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1`。
使用本机 Python、pandas、numpy、duckdb、pyarrow、pytest，`PYTHONPATH=.:src`。

当前任务以 `USER_REQUEST.md` 为准；旧 fixed multiplier grid 不再执行。

```sh
PYTHONPATH=.:src python -m research.portfolio_closure_v1.repair --gap IFCGR
PYTHONPATH=.:src python -m research.portfolio_closure_v1.repair --gap OGR
PYTHONPATH=.:src python -m research.portfolio_closure_v1.assemble
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.observe --gap IFCGR
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.observe --gap OGR
PYTHONPATH=.:src python -m research.portfolio_closure_v1.shadow --tag _unfunded_only
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.data
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.run --workers 3
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.analyze validate --workers 3
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.analyze rollforward --workers 3
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.analyze evidence --workers 3
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.stress
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.artifacts
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.analyze diagnostics
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.eligibility
PYTHONPATH=.:src python -m research.unified_opportunity_risk_v1.finalize
PYTHONPATH=.:src pytest -q research/unified_opportunity_risk_v1/test_engine.py research/portfolio_closure_v1/test_repair.py research/shared_capital_v1/tests/test_policy.py research/shared_capital_v1/tests/test_account_guards.py research/shared_capital_v1/tests/test_execution_facts_v1.py
```

`run.py` 会校验已有 receipt 的 contract/engine/calibration identity 后续跑；失败或中断未生成 receipt 的目录会重新计算。测试性前缀：`run --smoke`；独立完整 discovery 重跑：`run --case R0_RP75_S10_F0 --group determinism`。

原始注册输入来自 input_manifest.json 指定的只读路径；不复制或修改外部父工作树。大体积物理账户 parquet、原始路径和 liquidity 缓存保留在本地且不进入 Git，最终 manifest 绑定哈希。所有 required outputs、冻结合同、校准表、研究代码进入 Git。

SMV6 原生 context 中 set 的字符串顺序可能随 Python 进程变化；状态相等性按集合内容规范化核对，物理成交、现金、净值和持仓保持逐项核对。Native SuperMind 平台等价性未因此升级。

机器金额容差沿用权威账本：cash ≥ -1e-8 元，权益差≤1e-6元，数量差≤1e-8。现金从未clip；完整实际最小值保留在账户验证表。初次全流程复现可先运行测试，再运行finalize；已有test_results.json记录本次69项通过证据。
