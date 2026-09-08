# Reproduce this separate diagnostic

Working directory: `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1`.

```sh
PYTHONPATH=.:src /opt/anaconda3/bin/python -m pytest -q research/unified_opportunity_risk_v1/exposure_scale/test_scale.py research/unified_opportunity_risk_v1/test_engine.py research/portfolio_closure_v1/test_repair.py research/shared_capital_v1/tests/test_policy.py research/shared_capital_v1/tests/test_account_guards.py research/shared_capital_v1/tests/test_execution_facts_v1.py
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.exposure_scale.run --workers 3
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.exposure_scale.analyze
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.exposure_scale.report
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.exposure_scale.seal
```

The run command resumes only exact source/contract/input-bound completed receipts. A failed directory without a receipt is rerun. To independently recompute an account, preserve/move that account cache directory before running `run --scale 1` (or another fixed scale). Never alter the frozen calibration or existing Native verdict.

The parent `output/liquidity.parquet` and registered raw inputs are existing local dependencies. Source and receipt manifests bind the physical accounts; large parquet caches remain local and ignored by Git. Tables, raw cash provenance summaries, benchmark display data, code and figures are committed. Benchmarks are used only by the plotting stage.

The unused-cash table is a disclosed ordered constraint waterfall with cash provenance, not a rerun NAV or a uniquely identified causal decomposition. It retains signed constraint interactions. Gross and cash are algebraically redundant in this unlevered long-only ledger and receive no duplicate attribution. New cash released by Native exits is tagged NO_QUALIFYING_OPPORTUNITY until the next allocation; existing tags carry until the next decision. Each daily row reconciles exactly to actual cash under Native numerical precision.

用户明确确认：冻结原始信号来源，允许原生持仓状态改变合法请求。因此不锁死旧 B 的逐请求清单，不人为压制资金路径改变后的原生合法机会；opportunity_population_audit.csv 单列这些状态反馈差异。
