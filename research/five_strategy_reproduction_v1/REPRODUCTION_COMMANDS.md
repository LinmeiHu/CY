# 可重跑命令

以下命令均从相应仓库根目录运行，使用本轮实际带齐 pandas/numpy/duckdb/pyarrow/matplotlib 的解释器 `/opt/anaconda3/bin/python3`。输出根固定为新的复现目录，不覆盖旧账本。

## 1. 源码导出

```bash
cd /Users/linmei/Downloads/CY_Five_Strategy_Source_Recovery_Kit
/opt/anaconda3/bin/python3 recover_sources.py \
  --repo /Users/linmei/Documents/CY-worktrees/five-strategy-integration-20260906 \
  --out /Users/linmei/Downloads/CY_five_strategy_source_export_20260906
```

预期退出码为 2、结果为 `IDENTITY_CHECKS_INCOMPLETE`；已知原因是 ATRDR 身份记录提交时点，不代表入口源码缺失。不要把该状态改写成 PASS。

## 2. SMV6 冻结回调与影子账本

```bash
cd /Users/linmei/Documents/CY-supermind-v6
/opt/anaconda3/bin/python3 research/supermind_v6/scripts/run_v6_hybrid_annual_replay.py \
  --start 2010-01-01 --end 2026-08-28 \
  --qmt-root research/supermind_v6/data/market_data_qmt_v1 \
  --hybrid-root research/supermind_v6/data/market_data_hybrid_etf_longest_v1 \
  --hybrid-summary research/supermind_v6/manifests/v6_hybrid_critical_history_longest_summary.json \
  --events /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/events.parquet \
  --metrics /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/metrics.parquet \
  --summary /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/summary.json \
  --report /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/report.md \
  --pdf-root /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/pdfs \
  --skip-pdf

/opt/anaconda3/bin/python3 research/supermind_v6/scripts/build_v6_longest_equity_curves.py \
  --start 2010-01-01 --end 2026-08-28 \
  --qmt-root research/supermind_v6/data/market_data_qmt_v1 \
  --hybrid-root research/supermind_v6/data/market_data_hybrid_etf_longest_v1 \
  --events /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/events.parquet \
  --equity /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/equity_shadow.parquet \
  --annual /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/annual_shadow.parquet \
  --summary /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/equity_shadow_summary.json \
  --report /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/equity_shadow_report.md \
  --pdf /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/full/equity_shadow.pdf
```

## 3. SMV6 现金/整手本地语义

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-integration-20260906
PYTHONPATH=. /opt/anaconda3/bin/python3 \
  research/five_strategy_reproduction_v1/replay_smv6_cash_constrained.py \
  --start 2010-01-01 --end 2026-08-28 \
  --qmt-root /Users/linmei/Documents/CY-supermind-v6/research/supermind_v6/data/market_data_qmt_v1 \
  --hybrid-root /Users/linmei/Documents/CY-supermind-v6/research/supermind_v6/data/market_data_hybrid_etf_longest_v1 \
  --output-root /Volumes/quant/CY_quant_research/five_strategy_reproduction_v1/smv6/cash_full \
  --initial-cash 1000000 --lot-size 100 --fee-bps 0
```

## 4. OGR / MCB / ATRDR 原冻结 runner

安全包装器只把原 runner 的输出常量改到隔离复现根，输入、选择、成交和账户算法仍调用恢复的原函数。ATRDR 的 Bear 输入使用本轮由 DuckDB 对旧 Parquet 做的只读兼容重序列化副本；报告会继续标记 Bear 父链未重建。

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-integration-20260906

PYTHONPATH=. /opt/anaconda3/bin/python3 \
  research/five_strategy_reproduction_v1/replay_stock_frozen_layers.py ogr

PYTHONPATH=. /opt/anaconda3/bin/python3 \
  research/five_strategy_reproduction_v1/replay_stock_frozen_layers.py mcb

PYTHONPATH=. /opt/anaconda3/bin/python3 \
  research/five_strategy_reproduction_v1/replay_stock_frozen_layers.py atrdr
```

完整输入、输出和父链边界在 `source_chain.csv`。不要直接运行原 runner 的无参数默认主程序，因为那会写其原始 `EXT` 和仓库内 freeze/result/report 路径。

## 5. IFCGR 外层冻结验证

该入口必须在 runner、validator 和 registry 配套的历史工作树中验证；当前集成工作树会在进入 CY-065 前因 validator/registry 版本错配而失败。

```bash
cd /Users/linmei/Documents/CY-supermind-v6-autonomous-20260830
PYTHONPATH=. /opt/anaconda3/bin/python3 \
  research/market_behavior_os_v2/scripts/run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_root_seal_correction.py \
  verify-only \
  --asset-root /Users/linmei/Documents/CY/data/staging/CY-065-V29R2-ISSUER-FACT-ROLLFORWARD-ROOT-SEAL-CORRECTION-2022-2026-V1 \
  --parent-selected /Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v28_family_rollforward_through_20260904_v1/v28r2/selected_signals_2022_2026.parquet \
  --verification-root /Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_stage_a_verification_v1 \
  --output-root /Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_through_20260904_v1 \
  --expected-outer-freeze-sha256 e5d023957ee40df49d83cdc0231daa14bf331a6a6dc18be37561d609405408dd
```

这是只读验证命令；不要重复执行一次性 `stage-b` 封存命令。新复现根中的 IFCGR 成交与净值来自同一冻结选择中间层的独立 lane 重放。

## 6. 聚焦测试

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-integration-20260906
PYTHONPATH=. /opt/anaconda3/bin/python3 -m pytest -q \
  research/five_strategy_reproduction_v1/tests/test_smv6_cash_constrained.py \
  research/five_strategy_reproduction_v1/tests/test_replay_stock_frozen_layers.py
```

预期：`4 passed`。
