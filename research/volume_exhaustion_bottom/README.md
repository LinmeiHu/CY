# Volume Exhaustion Bottom V1

This lane tests whether declining A-share activity adds predictive information after a
meaningful decline. It is signal research, not a portfolio backtest or production strategy.

The fixed V1 experiment reads registered PIT-B daily asset `CY-006`, forms close-based
signals, and permits entry only at the next listed session's legal open. The final run
rehashes all nine frozen Parquet files and passes the repository's standard input-manifest
BACKTEST authorization.

Run from the repository root with the project's data-capable Python environment:

```bash
/Users/linmei/Documents/CY/.venv/bin/python \
  research/volume_exhaustion_bottom/experiment.py
```

Run the focused checks:

```bash
/Users/linmei/Documents/CY/.venv/bin/python -m pytest -q \
  research/volume_exhaustion_bottom/tests/test_v1_semantics.py
```

The quantitative conclusion is in [`reports/REPORT.md`](reports/REPORT.md). Exact signal
and outcome semantics are in [`methodology.md`](methodology.md); machine-readable results
are in [`reports/results.json`](reports/results.json).

