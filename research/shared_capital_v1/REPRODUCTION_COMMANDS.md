# 最终推进 V1 复跑

仅在本工作树和 `research/five-strategy-shared-capital-v1` 分支运行。

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.final_progress_v1
```

当前预期退出 **2**：PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE。命令验证冻结股票池、全量输入/官方原件/提取文本哈希，重建已有可信成交前缀的持仓公司行动审计，生成官方日期与两项单笔时间线，更新未闭合原生边界的工程状态，执行四套共同 P0 初始化门检查，两次确定性检查及全部聚焦/原单元测试。该命令依赖本机既有原生预资本/成交缓存，**不是完整冷启动回放，也不是 48 场景运行器**。

官方原文补录复跑（只取得研究截至 2023 的实施公告，不读取未来投资结果）：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.official_backfill
```

其输入为 `corporate_action_potential_envelope.csv`；已有原件复用并核对 hash，失败不能以网页校验文本冒充 PDF。原件存于已注册研究数据根 `/Volumes/quant/CY_quant_research/five_strategy_shared_capital_v1/official_ca`，没有其他工作树 Python 代码导入。若重新抓取到不同官方 bytes，必须审计变化，不能以当前抓取时间充当历史 alpha 可用时间。

聚焦与原测试：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m pytest -q research/shared_capital_v1/tests tests/unit
```

已有冷启动父信号命令（单独重建，不宣称闭合 P0）：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.build_inputs --strategy ATRDR
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.build_inputs --strategy MCB
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.build_inputs --strategy OGR
```

`close_baseline_v05/v06` 为历史流程，会覆盖报告并重新标记旧数据阻塞，不作为当前最终闭合命令。正式共同股票 raw 连续状态、SMV6 跨袖全阶段整合和 48 场景运行命令尚未完成，不能编造不存在的命令。

输出清单核验：在本目录下执行 `shasum -a 256 -c output_manifest.sha256`。重新运行会更新时间相关的 pytest XML，需重新生成清单后再对新运行封存；不能把旧清单强行解释为新结果通过。
