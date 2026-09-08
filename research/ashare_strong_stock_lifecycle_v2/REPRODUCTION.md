# Reproduction

```sh
PYTHONPATH=.:src python -m research.ashare_strong_stock_lifecycle_v2.run
PYTHONPATH=.:src python -m pytest -q research/ashare_strong_stock_lifecycle_v2/test_lifecycle.py
```

The run reads the existing V1 panel and authorized CY-006 cache. The event panel and other large artifacts are written under `/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v2`; Git keeps code and compact summaries.
