# USIC V5 实际运行命令

```sh
cd /Users/linmei/Documents/CY-worktrees/usic-d08-entry-timing-v5-20260908
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
```

使用 `/Users/linmei/Documents/CY/.venv/bin/python`，大件输出位于 `/Volumes/quant/CY_quant_research/usic_d08_entry_timing_v5`。以下入口均在本轮实际运行：

```sh
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_d08_entry_timing_v5.diagnostics
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_d08_entry_timing_v5.run
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_d08_entry_timing_v5.robustness
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_d08_entry_timing_v5.analyze
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_d08_entry_timing_v5.verify
```

测试命令：

```sh
/Users/linmei/Documents/CY/.venv/bin/python -m unittest research.usic_d08_entry_timing_v5.test_v5 research.usic_market_router_v4.test_v4 research.usic_multichampion_ashare_v3.test_v3 research.usic_multichampion_ashare_v3.test_tail -v
```

初次`run`完成0.5A账户，0.25A账户因600161公司行动事实缺口停止。确认2022-07-18上市日后，使用新`_CA`账户恢复；阻塞`result.json`不删除。重复执行`run`对已存在0.5A账户只保留结果，不改写。`verify`实际重放`E3_QUARTER_BAND_C10_E10_CA`和`E3_QUARTER_S1_C10_E10`，六类Parquet均与首次运行SHA256相同。

原行情矩阵、权益库和V3/V4完整账户没有复制进Git；身份由各`result.json`、V3/V4 manifest及`SAMPLE_PERMISSION_AUDIT.json`约束。审核包包含四个代表账户的实际字节，其余文件由清单给出路径、字节和哈希。
