# V0.6 reproduction

仅在 `/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1`，
分支 `research/five-strategy-shared-capital-v1` 运行。

完整注册输入重建、原生账户/边界、原始父信号前缀探针、两次确定性回放、测试与哈希：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.close_baseline_v06 --regenerate
```

当前预期退出码 **2**，`TASK_STATUS=PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE`。
600622 / 603368 原生公司行动状态缺失，另有报告列明的统一物理价格单位、SMV6 原生批次分阶段整合和四套共同 P0 独立多层对账欠项。
缺失数据、测试失败、输入变化或重跑不确定性不会成为成功；发生异常时非零退出。
命令不执行 P1/P2/P3，也不会用现金替换 ATRDR 来运行场景。

省略 `--regenerate` 会复用已有 ATRDR/MCB/OGR 父信号缓存，重新生成 Gap
原生入场/退出、账户、前缀与边界，再重复账户验证。这是缓存依赖重跑，
不能代替从空缓存开始的完整命令。两种命令均检查已注册输入 SHA256；
原始行情与执行读取限定至 2023，完整容器哈希不解析 post-2023 投资结果。
SMV6 合法注册行情目录仅作数据输入，不导入其他工作树代码。

聚焦测试（包含原测试、转换状态、统一调度及初始账户恢复）：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m pytest -q research/shared_capital_v1/tests tests/unit --basetemp research/shared_capital_v1/cache/pytest_v06 --junitxml research/shared_capital_v1/output/focused_tests_v06.xml
```

仅重做公司行动原始响应/生产代码取证：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.ca_forensic
```

仅检查四个共同 P0 初始化入口（当前均在初始化门前停止）：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.common_p0_v06
```

该子模块写 gate 状态，退出 0 只表示 gate 检查完成，不能表示 P0 通过；
正式闭合判定使用完整 V0.6 命令的非零退出和 task_status_v06.json。
`close_baseline_v05` / 原始 V0 inventory runner 保留用于历史审计，
会覆盖新版报告，不能用作本次闭合命令。

冻结经济策略、原生退出、policy 和 initial_state_v05 合同不改。
V0.5 的两个非经济验证修复已存在于本任务 START_HEAD，
本次对 START_HEAD 的所有冻结源码继续要求字节不变。
缓存、日志和大型账户明细保留在本目录且不提交；紧凑证据、源码和报告提交，不推送。
