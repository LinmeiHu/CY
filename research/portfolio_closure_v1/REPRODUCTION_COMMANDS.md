# 复现输入审计

```sh
cd /Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1
python research/portfolio_closure_v1/audit_inputs.py
python -m pytest -q research/portfolio_closure_v1/test_input_audit.py research/capital_admission_v1/test_gate_a.py research/capital_admission_v1/test_recovery.py
```

脚本只读取父研究数据，在当前 portfolio_closure_v1 目录写审计产物；不重跑写入父级 registered cache 的构建器，不需要重建旧 cache 软链接。父回归测试保留运行，但其预设 PASS 断言不等同研究有效性证明。原始数据挂载路径记录在 input_manifest.json。
