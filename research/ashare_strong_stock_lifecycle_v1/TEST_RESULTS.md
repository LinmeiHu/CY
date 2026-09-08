# Test results

`PYTHONPATH=.:src python -m pytest -q research/ashare_strong_stock_lifecycle_v1/test_lifecycle.py`

结果：`1 passed`。

该测试锁定 Outcome 在 Repair 分类完成后才开始，以及无 Repair 行仍保留在分母。输入层另由注册 CY-006 的 PIT-B 覆盖、重复、time-travel、consistency 和 cross-table gate 约束；本轮没有进入账户阶段，故不虚报 cash、lot、T+1、position 或公司行动账户测试为已运行。
