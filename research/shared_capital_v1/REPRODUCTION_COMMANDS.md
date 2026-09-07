# Reproduction

Run from the repository root. All new files stay under research/shared_capital_v1.
The existing configuration is read solely for input paths; no code is imported
from another checkout. The inventory rejects outcome tables as production inputs.

```bash
uv venv research/shared_capital_v1/.venv --python python3
uv pip install --python research/shared_capital_v1/.venv/bin/python --cache-dir research/shared_capital_v1/.uv-cache -r requirements.lock pytest==8.3.4
research/shared_capital_v1/.venv/bin/python research/shared_capital_v1/run_shared_capital_v1.py --stage all --period all --gap all --mcb-mode all --policy all --input-config research/five_strategy_exit_risk_v1/input_config.json --output-root research/shared_capital_v1/output
research/shared_capital_v1/.venv/bin/python -m pytest -q research/shared_capital_v1/tests
```

Expected inventory exit code is **2**, with PARTIAL_COMPLETE. It is not a
successful replay. All CLI selectors are accepted, but demand/replay currently
stop at inventory and expose their unimplemented status. report refreshes the
blocker report, not economic results. No historical metrics are emitted.

The first inventory invocation writes an immutable freeze receipt before any
outcome-bearing run. Later invocations reject changed economic policy or frozen
sources. Actual input-file hashes are checked before/after; untouched large
directories are explicitly outside the verified hash scope.

No commit/push command is included: the requested all-scenario completion gate
has not passed. The focused tests validate policy primitives and reproduce the
source-coverage blocker, not P0 or a physical-account replay.
