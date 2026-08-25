# 2020–2023 停牌缺量日研究版桥接策略

## 问题

2020–2023 日线中有 5,781 条记录缺少 `volume` 和 `amount`。审计显示这些记录全部满足：

- `trade_status = 0`；
- `current_day_data_tradable = false`；
- OHLC 价格存在且为正，且满足 OHLC 关系；
- 当前分钟日聚合源没有覆盖这些停牌日。

因此它们不是可由分钟线重建的成交量记录，不能把成交量猜成正常交易量，也不能把 `bar_valid` 或 `hard_valid` 改成 true。

## 研究版处理

在 `--research-relaxed` 下，若停牌日 OHLC、流通股本、公司行动和 `trade_status` 可用：

1. 以价格记录继续状态链；
2. 将成交量和成交额作为 0 输入；
3. `advance_chip_state` 的停牌分支保持 replacement fraction 为 0，因此沿用前一交易日筹码质量，不注入虚构新筹码；
4. 标记 `research_suspension_bridge=true`；
5. 保持 `daily_hard_valid=false`、`strict_sample=false`，不允许进入严格风险和实盘路径。

这解决的是状态链连续性，不是交易量数据恢复。停牌日仍不能产生新的成交信号；后续信号研究必须使用可交易日的 next-tradable-open 执行规则。

## 验证

- `python -m py_compile scripts/build_chip_state_features.py`：退出码 0。
- `PYTHONPATH=src pytest -q tests/test_chip.py tests/test_features.py tests/test_chip_peak_equivalence.py`：退出码 0，21 passed。

全市场特征生成和回测尚未运行，待短样本验证桥接行和统计覆盖变化后再决定是否扩大。
