# V12 chip storage capacity contract v1

Date: 2026-08-26

Contract version: `v12-chip-storage-capacity-contract-v1`

Owner: CYQ-GAME

Status: **FROZEN DESIGN / NOT IMPLEMENTED / NOT REGISTERED / PENDING INDEPENDENT REREVIEW**

This document freezes the capacity boundary for one completed, registered, production-usable chip bundle for one target year, the complete production universe, and all formal seller models. It does not certify the offline checkpoint prototype or any existing artifact for production.

## 1. Independent contracts

Passing one contract never implies passing another:

1. **Semantic correctness:** PIT/`available_at`, T+1/executability, corporate-action coordinates, three seller models, exact conservation, exact replay, lifecycle and temporal-tracker continuation, and fail-closed lineage/version checks.
2. **Final durable bundle capacity:** physical compressed logical bytes in the immutable completed bundle, checked by both actual and normalized gates.
3. **Dependency inputs:** shared registered daily, minute, corporate-action, and any other canonical-replay-required registered inputs. They are excluded from bundle bytes but always reported and bound by snapshot ID and digest.
4. **Workspace disk preflight:** existing occupancy plus free bytes required for projected final and temporary bytes. This is separate from the bundle gate.
5. **Validation evidence and historical artifacts:** not new-bundle bytes, but still real occupancy and never hidden from workspace preflight.

## 2. Thresholds and byte basis

- `TARGET_GIB = 45`
- `HARD_FAIL_GIB = 50`
- `GiB = 1,073,741,824 bytes`
- byte basis: sum of `stat().st_size` for every regular file in the immutable final bundle inventory after build

For each of `ACTUAL_BUNDLE_GIB` and `NORMALIZED_5210_EQUIVALENT_GIB`:

- `<= 45`: `TARGET_PASS`;
- `> 45` and `<= 50`: `WARNING_NOT_TARGET_PASS`;
- `> 50`: `HARD_FAIL`.

Both metrics are mandatory. Both must be at most 45 GiB for a target pass, and neither may exceed 50 GiB. Estimated values cannot satisfy this production gate.

Let `B` be actual durable bytes, `C` verified completed production symbol-days, `T_y` target-year trading days, and `N_ref = 5210`:

```text
NORMALIZED_5210_EQUIVALENT_GIB
  = B / C * (5210 * T_y) / 1073741824
```

The denominator must equal the independently verified completed set. Missing, duplicate, skipped, unexpected, or out-of-scope symbol-days fail closed and cannot reduce the result. Every symbol-day must contain seller models `UNIFORM`, `DISPOSITION`, and `ACTIVE_STICKY` in the frozen order.

## 3. Counted bundle and excluded reports

Counted classes are:

1. checkpoint state;
2. compact lossless daily journal/operator;
3. materialized annual daily feature asset;
4. a physical compatibility terminal whenever materialized;
5. checkpoint/journal and feature indexes;
6. artifact/dependency/parameter manifests and inventories;
7. build summary and registry binding;
8. all reader-required replay, transition, runtime, terminal, semantic, and schema metadata.

Excluded-but-reported classes are:

- shared registered daily inputs;
- shared registered minute inputs;
- shared registered corporate-action inputs;
- every other replay-required shared registered input explicitly named by the canonical replay manifest;
- staging, raw sources, build temporary files, validation-only evidence, benchmark/counterfactual output, logs, and old RC/backup/historical artifacts.

`included_asset_classes`, `excluded_but_reported_classes`, and `required_dependency_classes` have different duties: a replay dependency may be excluded from bundle charging only when it remains registered, immutable, digest-bound, retained, and separately reported. No excluded class may disguise a required bundle file.

The dependency report is:

```text
DEPENDENCY_INPUT_GIB
  = (daily dependency bytes
     + minute dependency bytes
     + corporate-action dependency bytes
     + other replay-required shared registered dependency bytes)
    / 1073741824
```

Corporate-action dependencies do not count toward 45/50 GiB, but they cannot be omitted. Every dependency binding names its asset ID, snapshot ID, exact content or inventory digest, coverage, and immutable path. Missing or mismatched dependencies fail closed; a mutable `latest` path is forbidden.

## 4. Dependency retention is not implemented yet

The current `configs/data_asset_registry.json` and `src/cyq_game/data/registry.py` validate registered assets and immutable input manifests but do **not** currently implement retention lifetime, expiry, dependency pin/lease, reverse dependency, GC protection, or dependency-before-bundle deletion enforcement. A prose promise is not sufficient.

The future `DependencyBinding` schema, pure validation types, and canonical serialization are defined in Phase 1. Production pin/lease, reverse-reference lookup, deletion ordering, and GC protection are implemented and tested in Phase 4. They are required before Phase 5 or any registered production gate:

```text
DEPENDENCY_RETENTION_ENFORCEMENT:
REQUIRED_BEFORE_PHASE_5_OR_ANY_REGISTERED_PRODUCTION_GATE
```

An active registered bundle prevents dependency deletion, expiry, or GC. Bundle registry binding must be removed before bundle deletion; the dependency pin may be released only after bundle deletion succeeds. Any interruption, stale pin, orphan reference, missing dependency, or digest mismatch fails closed.

## 5. Workspace formulas

The following names and definitions are normative in the JSON contract, this document, and the RFC:

```text
PROJECTED_FINAL_DURABLE_BYTES
PROJECTED_TEMPORARY_PEAK_BYTES
EXISTING_WORKSPACE_OCCUPIED_BYTES

REQUIRED_FREE_BYTES
  = 1.25
    * (PROJECTED_FINAL_DURABLE_BYTES
       + PROJECTED_TEMPORARY_PEAK_BYTES)

WORKSPACE_REQUIRED_BYTES
  = EXISTING_WORKSPACE_OCCUPIED_BYTES
    + REQUIRED_FREE_BYTES
```

Existing workspace occupancy is not new-bundle capacity, but it is part of the real disk-space preflight. It is added once and is not multiplied by 1.25. Temporary peak is part of required free space but never part of final durable bundle bytes. The workspace gate and the 45/50 GiB bundle gate are independent.

Small no-double-count example, in GiB: if existing occupancy is 100, projected final is 30, and temporary peak is 10, then `REQUIRED_FREE = 1.25 * (30 + 10) = 50` and `WORKSPACE_REQUIRED = 100 + 50 = 150`. Existing occupancy is not inside the margin term, and temporary bytes are not added to the final bundle.

`PROJECTED_TEMPORARY_PEAK_BYTES` remains `UNMEASURED`; therefore no numeric production workspace claim exists. For scenario `s` below:

```text
SCENARIO_s_REQUIRED_FREE_GIB
  = 1.25 * (SCENARIO_s_PROJECTED_FINAL_DURABLE_GIB
            + PROJECTED_TEMPORARY_PEAK_GIB)

SCENARIO_s_WORKSPACE_REQUIRED_GIB
  = EXISTING_WORKSPACE_OCCUPIED_GIB
    + SCENARIO_s_REQUIRED_FREE_GIB
```

## 6. Fixed-sample engineering interval

The 50-symbol design is not a probability sample. The mother frame contains 400 complete-year symbols sorted by old operator file size, split into ten size strata of 40 symbols each. Each stratum deterministically selects approximately the 1st, 11th, 21st, 30th, and 40th sorted positions. There is no random start, random sampling, inclusion probability, or design weight. The standard error does not account for probability-sampling stratification.

The only permitted label is:

```text
unweighted fixed-sample mean t-based engineering interval
未加权固定样本均值 t 型工程区间
```

It uses `n=50`, `df=49`, the Student-t 0.975 quantile, and observed sample dispersion. It is not a probability-sampling confidence interval, has no full-market frequency-coverage interpretation, cannot satisfy a production capacity gate, and is only an engineering dispersion/uncertainty envelope. Point, low, and high are all `ESTIMATED`; the production gate accepts only registered `ACTUAL` bytes.

Arithmetic inputs are:

```text
sum_total_bytes       = 388253116
mean_total_bytes      = 7765062.32
sample_sd_bytes       = 1823535.6161465554
standard_error_bytes  = 257886.8799824837
exact_t49             = 2.0095752371292392
```

`t_49=2.0096` may appear only as a display value and is not the calculation input. There is no intermediate rounding; only final display values are rounded. These estimates are not production actuals.

The corrected checkpoint-only 3,941-symbol endpoints are:

| Component | Low GiB | Point GiB | High GiB |
|---|---:|---:|---:|
| checkpoint+journal+prototype per-symbol manifest | 26.598307 | 28.500436 | 30.402566 |

## 7. Terminal policy and two capacity scenarios

The year-end checkpoint is canonical terminal state, but this does not authorize deletion of a physical terminal while a consumer still requires it. Every consumer must either migrate explicitly to a versioned checkpoint terminal adapter with exact round-trip tests, or continue receiving a mandatory counted physical compatibility terminal. Mixed implicit fallback is forbidden.

The planning constants frozen before final physical measurement are `0.161144 GiB` annual feature, metadata allowances `0.05/0.10/0.25 GiB` at low/point/high, and `3.453860 GiB` for the conservative current legacy terminal. The legacy value is a planning scenario, not a commitment to a future format. An unknown durable minimal view is measured and counted, never entered as zero.

### Scenario A: `STEADY_STATE_ADAPTER_OR_MINIMAL_VIEW`

Conditions: every physical terminal consumer has migrated and passed exact tests; the year-end checkpoint carries complete canonical state; no complete legacy cell payload is duplicated. A materialized minimal view, if any, is measured and added before a gate.

| Estimated bundle | Low GiB | Point GiB | High GiB | Expected status |
|---|---:|---:|---:|---|
| 3,941 actual | 26.809451 | 28.761580 | 30.813710 | envelope below target; no production pass |
| 5,210 normalized | 35.442081 | 38.022795 | 40.735709 | envelope below target; no production pass |

### Scenario B: `MIGRATION_PHYSICAL_COMPATIBILITY_TERMINAL`

Conditions: at least one physical consumer remains; a versioned physical compatibility terminal is mandatory and counted. Until its final format is measured, the current legacy-terminal bytes are the conservative planning input.

| Estimated bundle | Low GiB | Point GiB | High GiB | Expected status |
|---|---:|---:|---:|---|
| 3,941 actual | 30.263311 | 32.215440 | 34.267570 | envelope below target; no production pass |
| 5,210 normalized | 40.008082 | 42.588796 | 45.301710 | point below target, high enters warning; no production pass |

Scenario B's normalized engineering interval crosses into the 45–50 GiB warning band. Neither scenario is `TARGET_PASS`; the production `ACTUAL` and normalized gates have not run.

Because temporary peak is unmeasured, the scenario workspace results remain symbolic rather than fabricated numbers:

| Scenario | Required-free range GiB | Workspace-required range GiB |
|---|---|---|
| A | `1.25 * ((26.809451..30.813710) + PROJECTED_TEMPORARY_PEAK_GIB)`; point uses `28.761580` | `EXISTING_WORKSPACE_OCCUPIED_GIB + scenario_A_required_free_gib` |
| B | `1.25 * ((30.263311..34.267570) + PROJECTED_TEMPORARY_PEAK_GIB)`; point uses `32.215440` | `EXISTING_WORKSPACE_OCCUPIED_GIB + scenario_B_required_free_gib` |

These expressions recalculate the final-durable input for each terminal policy without inventing an unmeasured temporary peak.

## 8. Registration and release gates

Registration requires one immutable candidate root with complete inventory/digests, verified universe and three-model coverage, canonical replay parameter manifest and digest, dependency bindings and enforced retention, complete terminal schema, physical compatibility bytes when materialized, actual/normalized byte measurements, dependency/temporary/workspace reports, exact regression evidence, and a registry binding to the exact manifest digest.

Release fails closed on missing/expired/mutable/digest-mismatched dependencies; replay parameter mismatch; terminal omission; incomplete or mixed-version roots; PIT/`available_at` violations; non-bit-exact state, share, feature, lifecycle, or tracker replay; any conservation error; partial/duplicate shards; or an estimate presented as `ACTUAL`.

The owner is CYQ-GAME. Changes to thresholds, byte basis, included classes, normalization, sample label, dependency/retention policy, terminal policy, or failure behavior require a new versioned contract and independent review. This revision is not safe to commit or use to start Phase 1 until a separate independent rereview passes.
