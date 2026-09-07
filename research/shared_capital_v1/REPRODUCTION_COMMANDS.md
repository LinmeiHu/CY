# 最终连续账户与共享资金复跑

工作目录：`/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1`。

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.reproduce_v2
```

顺序：原始股数连续回放 → 两个历史前缀与边界 → 测试 → 四个独立共同 P0 对账 → 冻结 48 场景（确认 P0 复跑检查）→ 已有 P0/P2 设置的确定性复跑 → 决策与报告。确定性重复不是第 49 个参数设置。任何验证错误非零退出，不越过 P0 门槛。

聚焦测试：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m pytest -q research/shared_capital_v1/tests tests/unit
```

从研究目录校验输出：`shasum -a 256 -c output_manifest.sha256`。旧 V0/V05/V06/final_progress_v1 总控属于历史诊断，不是本次正式复跑入口；不要用它们覆盖最新状态。
