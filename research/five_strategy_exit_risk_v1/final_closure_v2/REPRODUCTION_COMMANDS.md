# 固定退出研究 Closure V2 复跑

工作目录与解释器：

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-exit-risk-v1
```

输入身份及每个文件哈希见 `input_manifest.json`。正常复跑使用外接盘中已经过滤至 2023-12-31 的原始数据快照、权威 reference 前缀，以及原来保留候选的完整股票账本；不需要另一个 worktree 的代码，不运行 Git 源码提取，不用 golden 事件驱动交易。

先确认 `/Volumes/quant` 已挂载，再按顺序执行：

```bash
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/run_closure.py smv
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/run_closure.py repeat
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/run_closure.py summarize
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/compare_accounts.py --smv6-candidate ENTRY_ATR_X1
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/audit_closure.py
PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest -q tests/unit/test_smv6.py research/five_strategy_exit_risk_v1/final_closure_v2/tests/test_closure.py
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/build_report.py
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/seal_closure.py
```

`repeat` 重新运行原生和四个候选的现金账户，比较 35 个核心结果的规范化哈希；不覆盖首轮大账本。`summarize` 只从完成账本计算统计口径，不改交易。`audit_closure` 对账并将缺失标价 episode 的官方 capital-days 留为 NA；保留外接盘原始中间表的已知标价和用于审计。`seal_closure` 运行同一组 focused tests 并保存输出、刷新报告及 hash manifest。

本轮使用已有冻结的候选合同，不重新生成合同或回写冻结时间。早期/全部授权历史有两日缺失净值，端点收益和 CAGR 可计算，完整路径风险保持 NA。2018–2021 和 2022–2023 组合分别运行，无几何串联。

首次建立快照时已经运行过以下命令；正常复跑不需要再次准备，不需要临时目录继续存在：

```bash
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/final_closure_v2/run_closure.py prepare --output-root /Volumes/quant/CY_quant_research/five_strategy_exit_risk_v1/20260907_final_closure_v2 --reference-root /private/tmp/five_strategy_bundle_causal_v2_ObqCh3/output/smv6
```

该初始命令仅作来源记录。若外接盘快照丢失，应先按 input manifest 找回相同身份的原始数据和权威基线，再明确提供恢复后的 reference 路径，不默认从过期的 769-event 目录重建。
