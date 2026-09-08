# 复现

从本工作树根目录执行，运行时为 `/opt/anaconda3/bin/python`，需已登记数据源和真实挂载 `/Volumes/quant`。基础库duckdb/pandas/numpy/pyarrow/matplotlib/Pillow/scipy来自现有环境。不要移动父工作树或修改其输入。

只读输入验证（会重写本研究检查回执；推荐交付核验）：

```sh
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.verify
```

统计重算（使用已冻结的既有盲评分，不是重新盲评）：

```sh
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.analyze_visual
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.visual_controls
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.path_labels
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.diagnostic_figures
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.sample_overlap
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.verify
```

准备阶段重建（会重写外盘派生样本/图像，只在独立复现副本执行；不要覆盖已封存证据）：

```sh
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.build coverage panel size sample
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.context
/opt/anaconda3/bin/python -m research.sixth_alpha_visual_discovery_v1.charts
```

准备脚本不打印个体封存结果。人工式视觉评分保留在open_coding_raw_labels.csv和formal_visual_labels.csv，无法用公式等价重生；样本和图像可按种子重建，标签只能原样核验。完成重新盲评需要未见结果的独立评估者和新研究版本。

`freeze_discovery.py`是一次性创建脚本，目录已存在即拒绝覆盖；**不要删除冻结目录来重跑**。全期覆盖补齐命令 `python -m research.sixth_alpha_visual_discovery_v1.complete_coverage`检查冻结提交存在，仅计算因果背景。`close_stages`生成0候选的状态凭证，不运行账户。

本轮没有策略或组合复现命令，因为没有合格策略；不能用父策略回测冒充第六策略验证。
