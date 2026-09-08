# Reproduction

从仓库根目录运行：

```sh
PYTHONPATH=.:src python -m research.ashare_strong_stock_lifecycle_v1.run
PYTHONPATH=.:src python -m pytest -q research/ashare_strong_stock_lifecycle_v1/test_lifecycle.py
```

运行会只读 `/Volumes/quant/CY_quant_research/usic_multichampion_ashare_v3/cache`，面板写到 `/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v1/strong_stock_panel.parquet`，小型摘要写到本目录。
