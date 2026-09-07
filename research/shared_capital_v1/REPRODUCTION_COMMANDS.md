# V0.5 reproduction

Run only from `/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1`,
branch `research/five-strategy-shared-capital-v1`.

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.close_baseline_v05 --regenerate
```

Expected exit code is **2**, with
`TASK_STATUS=PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE` while documented common P0
requirements remain open. Failed input chains or tests return nonzero. This
rebuilds historical raw parents, native entry/exit paths, IFCGR fact windows,
local SMV6 callbacks, all five independent physical accounts, actual prefix probes,
native continuous stock warmup from 2014, and validation.
It does not simulate an integrated common scheduler.

Without `--regenerate`, the command refreshes evidence from existing diagnostics
and reruns tests; it does not establish a fresh deterministic historical replay
or a before/after input hash check.

The original `run_shared_capital_v1.py` inventory runner is retained as a V0
reference. Its old report generator would overwrite the current report with the
inventory-only version. Use the V0.5 command above.

The economic policy and original freeze receipt remain byte-identical. Exact
before/after hashes for the two authorized non-economic repairs (`compare.py`,
`reproduce.py`) are in `contracts/validation_repair_receipt.json`. Strategy
sources, original producers, configs, manifests, and policy still fail closed on
any byte change.

The additional IFCGR raw route is registered CY-062, located through existing
CY-063/CY-065 routing manifests. Source schema and all parent 120-day windows are
checked before the unchanged classifier runs. No accepted-trade file supplies
opportunity parents. Historical daily/ETF reads are row-bounded through 2023;
no post-2023 investment outcome is parsed. Hashing the complete registered
container file does not evaluate its future investment outcomes.

Optional fresh environment setup (all packages pinned):

```bash
uv venv research/shared_capital_v1/.venv --python python3
uv pip install --python research/shared_capital_v1/.venv/bin/python --cache-dir research/shared_capital_v1/.uv-cache -r requirements.lock
```

Focused and existing unit tests:

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m pytest -q research/shared_capital_v1/tests tests/unit --basetemp research/shared_capital_v1/cache/pytest_tmp --junitxml research/shared_capital_v1/output/focused_tests.xml
```

Actual historical raw-bar prefix probes:

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.prefix_probe
```

Comparison-only CLI takes a JSON list of required specs with `layer`, `actual`,
`golden`, `keys`, optional `values` and `atol`:

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.shared_capital_v1.validation --spec /absolute/path/to/spec.json
```

Empty specs, duplicate/null keys, missing files, or failed comparisons return 1.
Production `reproduce.py` also records separate generation/comparison/causal/
account states and returns nonzero for required comparison failures. Do not run
its legacy all-interval ATRDR generator for this bounded study; that legacy
command includes registered post-2023 intervals.

Caches/logs remain inside this research directory and are ignored by Git.
Compact actual opportunity streams, reconciliations, hashes and reports are
committed. No push is performed.

User-confirmed initial-state rule is in `contracts/initial_state_v05.json`: native
continuous reconstruction; missing share-credit state blocks. Reset diagnostics
are controls only. This supplements the unchanged original policy initialization
clause without changing alpha, exits, allocation caps, fees, or risk rules.
