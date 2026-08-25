# CY engineering rules

## Core invariants

1. Never use data available after `decision_at`. Preserve `available_at`, `snapshot_id`, PIT semantics, and fail closed on unknown required lineage.

2. A signal formed on bar t cannot fill inside bar t. Preserve T+1, trading-status, limit, corporate-action, and real-executability rules.

3. Chip mass and ledgers must conserve exactly. Never hide errors with normalization, rounding, clipping, or relaxed tolerances.

4. Do not silently substitute missing or unregistered research inputs. Preserve `configs/data_asset_registry.json` input-governance semantics.

5. Do not weaken `hard_valid`, PIT checks, company-action handling, execution constraints, or existing safety contracts merely to make a test pass.

## Development workflow

For normal bug fixes and small changes:

- Read only files directly relevant to the task.
- Do not scan the whole repository unless necessary.
- Do not use subagents unless explicitly requested.
- Do not perform unrelated refactors.
- Prefer the smallest possible patch.
- Diagnose before modifying core state/migration logic.
- When diagnosing a divergence, find the first differing state/value before attempting a fix.
- Run the smallest targeted test first.
- Do not run full `pytest -q`, full `ruff check .`, `mypy src`, benchmarks, 10-stock rebuilds, or full-market rebuilds unless explicitly requested or preparing a final validation.

For a confirmed fix:

1. add/run the smallest regression test;
2. apply the minimal patch;
3. run directly related tests;
4. stop and report results.

Full repository validation is a separate explicit step.

## Protected areas

Changes to these require demonstrated root cause before modification:

- chip migration/state semantics;
- lineage/operator encoding;
- PIT/availability semantics;
- corporate-action coordinate handling;
- execution/fill semantics.

Do not change these layers based only on a hypothesis.

## Strategy semantics

Strategy states and participant interpretations are hypotheses, not facts. Preserve existing strategy semantics unless the task explicitly asks to change them.
