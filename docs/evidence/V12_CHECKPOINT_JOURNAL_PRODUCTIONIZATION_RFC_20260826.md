# V12 checkpoint+journal productionization RFC

Date: 2026-08-26

Status: **RFC / DESIGN ONLY / PHASE 0 / PENDING INDEPENDENT REREVIEW**

Capacity contract: `v12-chip-storage-capacity-contract-v1`

Selected architecture: periodic checkpoint + minimal lossless source-recompute journal + materialized annual daily feature + shared canonical compute stream + versioned resolver/index/manifests/registry

## 1. Scope, evidence, and non-goals

This revision resolves Phase 0 design blockers only. It does not implement a codec, writer, resolver, registry schema, retention engine, terminal adapter, build, benchmark, panel rebuild, or RC. No production source or test is changed in this round.

The protected 50-symbol prototype proved exact recomputation for its fixed sample and measured checkpoint+journal bytes. Its sample is a deterministic engineering sample, not a probability sample, and its estimates cannot pass a production capacity gate.

The current V12 full operator + feature + terminal estimate is 211.110968 GiB for 3,941 symbols. The checkpoint+journal point estimate before annual feature and new metadata is 28.500436 GiB. These are planning values, not registered actuals.

## 2. Version and root boundary

The new format is deliberately incompatible with the old full-width operator.

| Version field | Proposed value / rule |
|---|---|
| storage version | `chip-checkpoint-journal-storage-v1` |
| bundle schema version | `chip-checkpoint-journal-schema-v1` |
| artifact version | `v12-chip-bundle-checkpoint-journal-v1` |
| checkpoint codec version | `chip-checkpoint-codec-v1` |
| journal codec version | `chip-replay-journal-codec-v1` |
| terminal completeness version | `chip-terminal-completeness-v1` |
| dependency binding version | `chip-dependency-binding-v1` |
| dependency manifest version | `chip-replay-dependency-manifest-v1` |
| replay parameter manifest version | `chip-replay-parameter-manifest-v1` |
| transition semantics version | `real-chip-transition-semantics-v1` |
| replay contract hash | SHA-256 over the canonical version, parameter, dependency, schema, code-inventory, and runtime contract defined in section 5 |

No reader infers format from file names. It reads and validates the root manifest first. Old V12 and checkpoint+journal storage use separate immutable roots. A parent catalog may reference both, but a root containing mixed or unknown versions is rejected before payload read. Missing manifest or implicit fallback is forbidden.

## 3. Artifact and shared-compute boundary

### 3.1 Checkpoint

Each checkpoint is atomic, immutable, content-addressed, symbol/date scoped, and includes all three seller models in frozen order. It carries complete inventory cells and ordered lots, exact IEEE-754 share/economic bits, free-float and latent-supply ledgers, seller continuation, temporal peak tracker continuation, active lifecycle continuation, PIT/validity state, dependency identity, replay parameter manifest identity, versions, and exact state/inventory/tracker digests.

The cadence is opening state plus each calendar month-end trading session, including year end. Cadence is manifest data, never a reader default.

### 3.2 Journal

There is one logical row per completed production symbol-day. An ordinary row stores symbol/date/sequence; daily, minute, and corporate-action dependency bindings; decision/availability/trading state; checkpoint parent; replay/transition/runtime/parameter hashes; post-state, identity, share, feature, transition, and conservation digests for all three models; and explicit validity/reason fields.

Ordinary rows do not persist full daily state, destination vectors, retention vectors, or destination positions. A typed `explicit_override` is required when frozen dependencies and semantics do not uniquely reproduce the day. The only Phase 1 override classes are `CORPORATE_ACTION_COORDINATE_CHANGE`, `MULTI_ARC_TRANSITION`, `INVENTORY_ADJUSTMENT`, `IDENTITY_COLLISION`, `MISSING_SOURCE_TOPOLOGY`, and `NON_ORDINARY_DESTINATION`. Unknown override type/version or unmatched precondition fails closed.

### 3.3 Annual feature and writer stream

One canonical per-symbol stream prepares the day and advances the three seller models once:

```text
registered immutable inputs -> one day preparation -> one three-model transition
                                                   |-> checkpoint/journal sink
                                                   `-> annual feature accumulator/sink
```

Journal and feature sinks never run separate transitions. The feature preserves PIT lineage, typed canonical peaks, temporal tracker fields, seller disagreement, quality and reason codes. Per-symbol shards consolidate to a versioned annual feature plus exact inventory and manifest. Panel reads that annual feature and its registered daily/corporate-action inputs; it never opens checkpoint or journal payloads.

### 3.4 Indexes, manifests, summary, and registry binding

The new index maps symbol/year/date ranges to checkpoint and journal shards, sizes, digests, row groups, dependency manifest, and replay parameter manifest. The legacy operator index is not reused or overwritten. Artifact and feature manifests inventory every counted file. The build summary records expected/completed symbol-days, models, failures, overrides, resume events, exact gates, final/dependency/temporary/workspace bytes, RSS/runtime, terminal policy, and status. Registry binding names exact immutable roots and manifest digests; mutable aliases are forbidden.

## 4. Dependency binding, retention, and deletion contract

Required dependency classes are shared registered daily inputs, minute inputs, corporate-action inputs, and every additional shared registered input explicitly referenced by canonical replay. Corporate-action inputs are excluded from 45/50 GiB bundle charging but are always reported and bound by snapshot ID and content/inventory digest.

```text
DEPENDENCY_INPUT_GIB
  = (daily dependency bytes
     + minute dependency bytes
     + corporate-action dependency bytes
     + other replay-required shared registered dependency bytes)
    / 1073741824
```

The current registry and loader do **not** implement retention lifetime, expiry, pin/lease, reverse dependency, GC protection, or dependency-before-bundle deletion enforcement. This RFC does not describe those as existing capabilities.

Phase 1 defines a pure, non-activating `DependencyBinding` with these mandatory semantics:

| Field | Required meaning |
|---|---|
| `dependency_class` | closed enum for daily, minute, corporate action, or explicitly versioned additional replay input |
| `asset_id` | registered immutable asset identity |
| `snapshot_id` | exact snapshot identity; never `latest` |
| `content_digest` | SHA-256 of a single content object or canonical content inventory |
| `inventory_digest` | SHA-256 when dependency is a multi-file inventory; explicit null only when inapplicable |
| `registry_binding_version` | registry schema and exact registry revision/hash |
| `retained_until` / `retention_policy_id` | explicit lifetime or immutable policy identity; one must be present |
| `dependent_bundle_id` | exact bundle whose replay requires the dependency |
| `dependency_created_at` | immutable source creation timestamp |
| `dependency_registered_at` | registry binding timestamp |
| `immutable` | must be `true` |
| `deletion_protection_state` | `PINNED`, `RELEASE_PENDING`, or `RELEASED`; active bundle requires `PINNED` |

Deletion ordering is normative:

1. While a registered bundle exists, its dependencies cannot be deleted, expired, or garbage-collected.
2. Dependency GC queries reverse references and refuses an active dependent bundle.
3. Before deleting a bundle, remove its active registry binding through an atomic/versioned operation.
4. Delete the bundle successfully before releasing its dependency pin.
5. Any intermediate failure fails closed and leaves protective state in force.
6. Orphan bundle references and missing dependencies are forbidden.
7. Mutable aliases and mutable `latest` paths are forbidden dependencies.

Phase assignment:

- Phase 1: schema and pure validators only; no registry activation or production deletion change.
- Phase 4: implement pin/lease, reverse references, deletion ordering, and GC protection; migrate or wrap registry/loader paths.
- Phase 6: inject missing dependency, digest mismatch, premature delete, GC while active, successful bundle-delete-then-release, interrupted delete, stale pin, orphan-reference, and reverse-reference corruption failures. Reverse-reference corruption validation fails closed.

For Phase 6, `reverse-reference corruption` includes: a missing reverse edge for an active bundle; a reverse edge naming the wrong dependent bundle; a reverse edge naming the wrong dependency; a stale or extra reverse edge; disagreement between the forward dependency binding and reverse dependency index; and a reverse-index digest, generation, or version mismatch. Every such corruption makes dependency validation fail and blocks dependency GC and dependency deletion. Bundle registration, read, and deletion do not fall back automatically; in particular, a corrupt reverse index is never interpreted as “no dependency.” Silent repair is forbidden. The registry fails closed until an explicit registry repair or rebuild completes and both forward and reverse bindings are revalidated.

```text
DEPENDENCY_RETENTION_ENFORCEMENT:
REQUIRED_BEFORE_PHASE_5_OR_ANY_REGISTERED_PRODUCTION_GATE
```

Phase 5 cannot start until Phase 4 retention enforcement and its focused tests pass.

## 5. Canonical replay parameter manifest and hash

### 5.1 Canonical encoding

Phase 1 defines canonical JSON as UTF-8, no insignificant whitespace, lexicographically sorted object keys, and arrays in declared semantic order. Integers serialize as base-10 signed integer strings. Boolean and null use JSON literals. Dates use ISO `YYYY-MM-DD`; aware timestamps use UTC ISO-8601 with six microseconds and `Z`. Every float serializes as `f64be:` plus exactly 16 lowercase hexadecimal digits of its IEEE-754 binary64 big-endian bits; NaN and infinity are forbidden. Enums serialize as their exact case-sensitive value plus owning enum version. Sets are converted to sorted arrays using the encoded element bytes. Maps use canonical key order.

The parameter manifest includes its schema version, all rows below, exact dependency manifest digest, dependency content/inventory digests, code inventory digests, runtime inventory, and owner/version. `parameter_manifest_sha256` is SHA-256 over canonical bytes with that digest field omitted. The final replay contract hash includes the parameter-manifest digest. Writer and reader recompute and compare both digests before replay; mismatch fails closed. Defaults are serialized exactly like explicit values.

### 5.2 Read-only audit of current production/prototype call chain

The table enumerates the replay-impacting runtime values found in `scripts/build_real_chip_year.py`, `scripts/prototype_chip_checkpoint_recompute.py`, and their imported migration/state/price/feature/peak path. `INCLUDED = YES` means the exact canonical value is in the replay parameter manifest. Operational-only partitioning values are recorded in the build/resume manifest with `INCLUDED = NO` because they cannot alter canonical per-symbol replay; output digest equivalence is still required.

| Parameter | Source file/function | Canonical name | Canonical value serialization | Included in replay hash | Owner/version |
|---|---|---|---|---|---|
| target scope | `build_real_chip_year.main`, prototype `main` | `scope.target_year`, `scope.end_date`, `scope.emit_start_date`, `scope.symbols` | integer string; ISO date/null; symbols sorted exact strings | YES | builder scope v1 |
| warmup policy | builder `--warmup-start`, `_run_symbol`; prototype opening replay | `warmup.start_year`, `warmup.first_positive_float_rule`, `warmup.emit_rule` | integer; `FIRST_POSITIVE_FLOAT_INITIALIZES_THEN_NEXT_DAY_ADVANCES`; target-only emission | YES | transition v1 |
| continuation parent | builder `_resolve_resume_root`, `_read_terminal_snapshots`; new resolver checkpoint selection | `continuation.parent_bundle_id`, `continuation.parent_checkpoint_digest`, `continuation.selection_mode` | exact IDs/digest plus enum `EXPLICIT`, `AUTO_ADJACENT_YEAR`, or `NONE`; `NONE` allowed only under frozen initialization rule | YES | continuation v1 |
| dependency bindings | `_stage_inputs`, `_snapshot_ids`, `_minute_bars`, `_inventory_events` | `dependencies.bindings` | ordered `DependencyBinding` objects plus content/inventory digests | YES | dependency manifest v1 |
| model and grid versions | builder constants | `model.version`, `grid.version` | `real-chip-inventory-v2.1`; `log-grid-25bp-v1` | YES | builder/current semantic epoch |
| seller model order | `ensemble_v2.SELLER_MODEL_ORDER` | `seller_models.order` | `[UNIFORM,DISPOSITION,ACTIVE_STICKY]` | YES | ensemble v2 |
| maximum holding age | `migration_v2.DailyMigrationEngine.__init__` | `migration.max_holding_days` | integer `180` | YES | transition v1 |
| purchase split | `DailyMigrationEngine.__init__`, `_purchase_lots` | `migration.active_purchase_fraction` | f64 bits for `0.7`; complement computed under frozen operation order | YES | transition v1 |
| initial unknown-cost allocation | `migration_v2.initial_unknown_snapshot` | `initialization.allocations` | uniform/disposition `NEUTRAL=1.0`; active-sticky `ACTIVE=0.35,STICKY=0.65`; holding `-1`; prior units equal weights | YES | state v3 |
| uniform seller hazard | `DailyMigrationEngine._seller_hazard` | `seller_hazard.uniform` | f64 bits for constant `1.0` | YES | model v2.1 |
| disposition seller hazard | `_seller_hazard`, `_migration_kernel.disposition_path_no_saturation` | `seller_hazard.disposition` | `exp(clamp(1.5*pnl,-2.0,2.0))`; unknown cost hazard `1.0` with each float bit encoded | YES | model v2.1 |
| active/sticky hazard | `_seller_hazard`, `_active_sticky_path_no_saturation` | `seller_hazard.active_sticky` | ordered `ACTIVE=2.0,NEUTRAL=1.0,STICKY=0.25` | YES | model v2.1 |
| T+1 sale/purchase boundary | migration module contract and advance methods | `execution.same_day_resale` | enum `FORBIDDEN`; fixed PRE sale pool; purchases accumulated for POST only | YES | transition v1 |
| price grid | `StableLogPriceGrid`, builder `_run_symbol` | `grid.reference_price`, `grid.step_pct`, `grid.bucket_rounding` | f64 `1.0`, f64 `0.0025`, `floor(log(price/ref)/log1p(step)+0.5)` | YES | grid v1 |
| economic bucket | `bucket_for_economic_break_even` | `grid.nonpositive_economic_bucket`, `grid.economic_decode` | integer `-2147483648`; decode `0.0`; positive values use price grid | YES | grid v1 |
| float comparison policy | `state_v2.tolerance` | `numeric.abs_tolerance`, `numeric.rel_tolerance` | f64 `1e-6`; f64 `1e-12`; formula `max(abs,rel*max(1,abs(reference)))` | YES | state v3 |
| exact float/state encoding | state IDs; prototype `_f64_bits`, `_update_hash` | `numeric.float_encoding`, `numeric.comparison` | IEEE-754 binary64 bits; bit equality where exact contract requires; no float32/normalization | YES | codec v1 |
| stable cell identity | `state_v2.stable_cell_id` | `identity.cell_id` | SHA-256 of sorted compact JSON with economic float `.hex()`, first 8 bytes big-endian masked to 63 bits | YES | state v3 |
| lot ordering and compaction | `_compact_*lots*`, `SparseChipInventory.canonical` | `identity.compaction` | drop nonpositive; stable sort/group by stable cell ID; merge only identical dimensions/age-cap collisions; compensated sums in declared order | YES | transition v1 |
| stable summation/residual | `_migration_kernel.stable_sum`, `_bridge_residual_with_bounds` | `numeric.summation`, `numeric.residual_bridge` | compensated algorithm version; bounded single argmax correction; source bounds enforced | YES | transition v1 |
| corporate-action coordinate | `price_coordinate.rebase_economic_price` | `corporate_action.coordinate` | version `causal-economic-price-v2`; `(C-D)/R`; all operands f64 bits | YES | price coordinate v2 |
| action identity and order | `canonical_action_component_id`, builder `_inventory_events` | `corporate_action.identity_order` | sorted source IDs; event order cash at `09:00:00`, split at `09:00:01`, float bridge at `09:00:02`; SHA-256 payload | YES | price coordinate v2 / builder |
| float bridge/removal | builder `_inventory_events`, `_pro_rata_removals` | `corporate_action.float_bridge` | compare expected vs prior*ratio using frozen tolerance; sorted cell IDs; last residual assignment | YES | builder transition v1 |
| minute ordering and price | builder `_minute_bars`; `prepare_minute_path` | `minute.path_price_policy` | unique timestamp order; VWAP `amount/volume` clamped to `[low,high]`; absent VWAP uses OHLC4 | YES | builder minute path v1 |
| invalid minute fallback | `_minute_bars`, `_daily_fallback_bar` | `minute.invalid_path_policy`, `minute.daily_fallback_policy` | any invalid bar rejects whole intraday path; positive daily volume uses 15:00 daily bar and in-range VWAP else close | YES | builder minute path v1 |
| zero volume and suspension | `_run_symbol`, `prepare_minute_path`, migration advance | `trading.zero_turnover`, `trading.suspension` | empty path, no fabricated sale/purchase; registered state/quality still advances under frozen event rules | YES | transition v1 |
| turnover cap | `_cap_prepared_minute_path` | `minute.turnover_cap` | trigger `volume > float+tolerance`; capped volume `float*(1-1e-9)`; scale all volumes once | YES | builder minute path v1 |
| decision/availability times | builder `_aware`, `_event_available`, `_run_symbol` | `pit.session_times` | Asia/Shanghai; decision 15:00; action/float times above; require `available_at <= decision_at` | YES | PIT contract v1 |
| hard-valid and reason propagation | `_run_symbol`, `_quality_state_from_mass` | `quality.fail_closed_policy` | missing positive float on hard-valid row errors; reasons sorted; hard-valid only with no reasons; research-recoverable reason codes are bound separately below | YES | state v3 |
| research-recoverable quality reason-code domain | `scripts/build_real_chip_year.py::_RESEARCH_RECOVERABLE_QUALITY_CODES` | `quality.research_recoverable_reason_codes` | Semantic type: closed ordered array of quality reason-code enum/string values controlling which reasons allow annual-feature `research_valid` to remain or become true, thereby affecting feature semantics, logical digest, and the registered asset contract even though the set need not change lot-migration numerics. Domain version: `quality-reason-code-domain-v1`. Exact current members: `UNKNOWN_COST_INITIALIZATION`, `UNKNOWN_COST_PRESENT`, `TURNOVER_CAPPED_AT_FLOAT`. Canonicalize each enum's exact `.value` (or the exact value for an already-string member), sort by UTF-8 byte lexical ascending order independent of Python set/frozenset iteration, and serialize as the UTF-8 JSON array `["TURNOVER_CAPPED_AT_FLOAT","UNKNOWN_COST_INITIALIZATION","UNKNOWN_COST_PRESENT"]` with no extra whitespace, locale-dependent ordering, aliases, or unknown codes. The parameter-manifest digest includes the canonical name, domain version, and ordered array; replay and feature contract hashes bind that parameter-manifest digest. Writer validation requires the current constant's member set to equal the manifest exactly and fails closed during manifest generation on missing, extra, alias, or unknown values. Reader validation checks the parameter-manifest digest, domain version, and ordered canonical array and fails closed on any mismatch, missing, extra, or unknown code; it never substitutes the current code default when the artifact parameter is absent. | YES | `quality-reason-code-domain-v1` |
| checkpoint cadence | prototype `replay_target`; RFC writer manifest | `checkpoint.cadence` | `OPENING_PLUS_EACH_CALENDAR_MONTH_END_TRADING_SESSION_INCLUDING_YEAR_END` | YES | checkpoint schema v1 |
| journal override set | RFC section 3.2 / Phase 1 schema | `journal.override_classes` | exact six-value ordered enum listed in section 3.2 | YES | journal schema v1 |
| distribution feature parameters | `profile_metrics.compute_distribution_metrics` | `feature.distribution_parameters` | quantiles `[0.01,0.10,0.50,0.90,0.99]`; ASR `[0.9,1.1]`; concentration multiplier `1.20`; structural score `0.12`; smoothing `[1,4,6,4,1]` | YES | feature v6 |
| canonical peak parameters | `peaks.detect_canonical_peaks`, `dominant_canonical_peak` | `feature.peak_definition_parameters` | kernel `[1,4,6,4,1]`; offsets `[-2,-1,0,1,2]`; min mass `0.03`; min prominence `0.003`; valley ratio `0.80`; max span `1000000`; tie rounding `12` | YES | peak definition v2 |
| temporal peak parameters | `peaks.TemporalPeakTracker`, `_match_score`, `_ensemble_candidates` | `feature.peak_track_parameters` | ambiguity mass `0.02`; match permitted floor `0.03`; nonoverlap log limit `0.01`; score tie `0.05`; one-to-one ensemble rule; exact versions | YES | peak track v2 |
| feature ensemble aggregation | `daily_feature_fact._ensemble_row` | `feature.ensemble_aggregation` | median scalars; min known/model quality; max-minus-min spreads; all-model hard/research validity; sorted union reasons | YES | feature v6 |
| state codec semantics | prototype `_checkpoint_arrays`, `write_journal`, `_f64_bits`, `_time_code`, `_StringPool`; Phase 1 codec schema | `storage.state_codec` | format version; complete field-to-dtype map in canonical key order; integer endian; f64 stored as uint64 bits; UTC microsecond timestamps; UTF-8 string insertion/order rules; offsets; `allow_pickle=false`; schema-map digest | YES | checkpoint/journal codec v1 |
| code inventory | imported production/prototype call chain | `runtime.code_inventory` | root-relative path plus SHA-256 for builder, migration kernel/state, price coordinate, feature/profile/peak, semantic and codecs | YES | replay manifest v1 |
| runtime inventory | Python/NumPy/PyArrow/DuckDB/Numba/platform | `runtime.environment` | exact package/interpreter versions, platform/architecture, byte order, and build identifiers | YES | replay manifest v1 |
| workers/buckets/scheduling | builder/prototype CLI | `build.operational_partitioning` | explicit integers/mode in build/resume manifest | NO | operational only; per-symbol output digest must remain identical |
| legacy operator checkpoint interval | builder `CHECKPOINT_INTERVAL_DAYS` / `_output_row` | `oracle.legacy_checkpoint_interval_days` | integer `20` in independent legacy-oracle manifest | NO | oracle physical layout only; new cadence is the hashed month-end rule above |
| parquet row group/compression for final bundle | builder constants/future codec | `build.physical_layout` | integer row group, compression codec/level, dictionary flag in artifact manifest | NO | capacity/physical identity, not replay state; file digests remain mandatory |

For the audited current call chain, `REPLAY_PARAMETER_UNKNOWN_COUNT = 0`. A future code or configuration path that introduces a replay-impacting value not represented by the schema is a blocking unknown: build and registration fail until the table/schema/version is amended. “Relevant configuration” and “etc.” are not permitted substitutes.

## 6. Exact replay and reader architecture

Replay validates root, inventories, versions, parameter manifest and digest, dependency bindings/digests/retention, checkpoint/journal digests, seller order, and requested interval before state restoration. It selects the latest checkpoint at or before the required anchor boundary, never shortens lineage silently, restores complete three-model state/tracker/lifecycle continuation, and advances ordered journal days using only decision-time-available inputs.

After every model/day it compares transition, post-state, identity, share, feature, conservation, tracker, and lifecycle digests. Corporate actions use registered provenance and frozen coordinates. Missing input, parameter mismatch, invalid date, unsupported override, conservation error, or ambiguous topology returns no substitute state.

Add a new `CheckpointJournalChipLineageResolver` behind a manifest-driven resolver factory. Preserve the current `PersistedChipLineageResolver` for explicitly selected legacy roots. `StreamingLineageSession`, exact replay, signals, research, semantic/current/exact features, and terminal reconstruction route through the verified factory. A new-root error never triggers legacy fallback.

## 7. Terminal completeness and compatibility contract

Year-end checkpoint is canonical terminal state. Compatibility terminal is mandatory until every physical terminal consumer has either migrated to a versioned adapter or received a counted versioned physical compatibility file. A theoretical derivation does not permit omission unless a deterministic derivation contract, independent exact round-trip test, and migration of every consumer all exist. Mixed implicit fallback is forbidden.

### 7.1 Legacy field matrix and checkpoint requirement

The current physical schema is `scripts/build_real_chip_year.py:TERMINAL_SCHEMA`. “Absent” means the new checkpoint must add it or a separately versioned completeness component; it may not be silently inferred.

| Semantic field | Current physical terminal | New canonical terminal requirement / release rule |
|---|---|---|
| storage/model/grid version | `storage_version`, `model_version`, `grid_version` | preserve plus checkpoint/schema/artifact/replay/parameter/transition versions |
| seller model | `seller_model` | all three in frozen order; missing/duplicate fails |
| target/terminal date | `trading_date` | exact year-end trading date and target year |
| decision boundary | `decision_at` | preserve aware timestamp exactly |
| available boundary | `available_at` | preserve; must not exceed decision boundary |
| effective boundary | `effective_at` | preserve aware timestamp exactly |
| phase | `phase` | must be versioned and `POST` for terminal continuation |
| snapshot identity | `snapshot_id` | preserve plus checkpoint digest/parent identity |
| input IDs | `input_snapshot_ids` | preserve complete ordered IDs |
| input content/inventory digests | absent | mandatory dependency bindings and digests; no ID-only claim |
| free float / latent supply | `free_float_shares`, `latent_supply_shares` | exact binary64 bits and conservation ledgers |
| PIT grade | `pit_grade` | preserve exact enum/version |
| hard validity | `hard_valid` | preserve; never upgraded by adapter |
| reason codes | `quality_reason_codes` | complete sorted/versioned set; absence not success |
| complete cells | `cells` list | complete canonical cells/lots for each model; no lossy dedupe |
| cell identity | nested `cell_id`, `cost_bucket_id`, `holding_days`, `sensitivity` | preserve stable identity/dimensions and deterministic order; current reader recomputes `cell_id`, so removal waits for consumer migration and exact derivation tests |
| acquisition cost | nested `acquisition_cost` | exact binary64 bits; null semantics explicit |
| initialization prior units | nested `initialization_prior_units` | exact binary64 bits |
| exact shares | nested `shares` binary64 physical values | preserve exact bits and ordered-lot association |
| economic coordinate/bucket | nested `economic_break_even`; no explicit economic bucket | preserve exact economic bits and coordinate version; if bucket is derived, freeze formula/version and prove exact round trip |
| seller continuation | represented only by seller model plus terminal inventory | checkpoint must include every non-derivable seller/kernel continuation value; omission requires exact derivation proof |
| temporal peak tracker continuation | absent | mandatory previous peaks, base track, action IDs, split/merge/lost/reappear/ambiguity state and versions |
| lifecycle continuation | absent | mandatory active anchor IDs, bounds, identity/share/retention/destination continuation needed by current lifecycle consumers |
| semantic/runtime fingerprint | partial storage/model/grid only | complete semantic fields, replay parameter manifest digest, code inventory, runtime fingerprint |
| dependency retention state | absent | mandatory binding identity and verified pinned state before production use |

### 7.2 Physical consumers and migration

| Consumer | Current physical read/assumption | Phase and migration | Exact test | Rollback | Stop materialization only when |
|---|---|---|---|---|---|
| `scripts/build_real_chip_year.py` | `_read_terminal_snapshots` reads every legacy schema field and all cells to seed adjacent year | Phase 4: route new roots through checkpoint terminal adapter; legacy path stays explicit | every field/bit, three-model, adjacent-year uninterrupted-vs-resumed parity | select legacy builder/root | adapter parity and fail-closed version/dependency tests pass |
| `scripts/freeze_current_chip_asset.py` | requires physical terminal file counts per year and inventory inclusion; does not inspect cell fields | Phase 4: validate canonical checkpoint inventory or counted compatibility inventory explicitly | file-set, symbol-set, digest, coverage, deletion refusal | keep current freeze path and physical terminals | freeze contract recognizes checkpoint inventory and exact candidate passes |
| `scripts/assemble_real_chip_multiyear_root.py` | requires part/terminal symbol-set parity before assembly | Phase 4: versioned checkpoint/compatibility inventory parity; no mixed fallback | year/symbol parity, missing/duplicate/mixed-version failures | keep legacy assembly | new assembly contract and tests pass for every year |
| `scripts/merge_real_chip_year_roots.py` | hard-links physical terminal tree and enforces part/terminal parity | Phase 4: merge checkpoint roots or counted compatibility terminal tree under explicit version | link inventory/digest equality, duplicate conflict, interrupted merge | keep legacy merge | new merge is atomic, exact, and all downstream consumers migrated |
| `scripts/reconstruct_chip_terminals_from_lineage.py` | reads legacy operator, writes and rereads every legacy terminal field | Phase 4: checkpoint adapter/export tool; physical export counted when used | exact field/bit round trip and source replay parity | retain legacy-only script or explicit old tool | no registered consumer requests physical export |
| `scripts/audit_v13_oracle_retention.py` | validation-only audit reads prototype checkpoint/retained terminal inventories | Phase 6 `REVIEW_ONLY`; do not make it a production reader | retained-evidence digest and terminal/checkpoint parity | retain protected audit unchanged | independent replacement evidence exists; historical evidence remains untouched |
| `scripts/register_current_chip_asset.py` and registry loader | register/freeze inventory paths and digests; internal terminal fields are not parsed | Phase 4/8: bind terminal completeness and compatibility policy in manifest/registry | missing file/digest/version/pin failures | keep old immutable asset registration | new binding validates checkpoint completeness and consumer state |
| `tests/test_real_chip_storage.py` | exercises legacy writer/reader, v11 compatibility, terminal-only and adjacent-year resume | Phase 2/4 targeted new tests; legacy tests remain | all fields, exact bits, three models, year boundary, corrupt/missing/version failure | revert new tests with phase | new suite passes and independent review accepts release gate |

Current `src/cyq_game/strategy/chip_lineage.py` and `src/cyq_game/chip/operator_index.py` do not directly parse the physical terminal Parquet; they consume operator/index lineage. They still require migration to the new resolver/index contract and lifecycle parity before legacy terminal materialization can stop.

```text
TERMINAL_RELEASE_GATE:
ALL_PHYSICAL_CONSUMERS_MIGRATED_WITH_EXACT_TESTS
OR_MANDATORY_COUNTED_VERSIONED_PHYSICAL_COMPATIBILITY_TERMINAL
```

## 8. Capacity, statistical label, and workspace

All numbers in this section are `ESTIMATED`, not production `ACTUAL`.

The mother frame has 400 complete-year symbols sorted by old operator size, divided into ten 40-symbol size strata. About the 1st, 11th, 21st, 30th, and 40th positions in each stratum were fixed in advance. There was no random start, random sampling, inclusion probability, or design weight; the standard error does not account for probability-sampling stratification.

The interval is an `unweighted fixed-sample mean t-based engineering interval` (`未加权固定样本均值 t 型工程区间`). It uses `n=50`, `df=49`, Student-t 0.975, and sample dispersion. It is not a probability-sampling confidence interval, has no full-market frequency-coverage interpretation, is not a statistically guaranteed range, and cannot pass production capacity. Point/low/high are all estimates.

The calculation uses exact `t49 = 2.0095752371292392`; displayed `t_49=2.0096` is not an input. Inputs and all intermediate calculations retain full precision; rounding occurs only for display.

| Checkpoint engineering estimate, 3,941 | Low GiB | Point GiB | High GiB |
|---|---:|---:|---:|
| checkpoint+journal+prototype per-symbol manifest | 26.598307 | 28.500436 | 30.402566 |

Planning additions are an exact decimal `0.161144 GiB` annual feature and `0.05/0.10/0.25 GiB` metadata low/point/high. The conservative current legacy terminal planning value is exact decimal `3.453860 GiB` at 3,941. It is not a future-format promise.

### Scenario A — `STEADY_STATE_ADAPTER_OR_MINIMAL_VIEW`

All consumers migrated; year-end checkpoint is complete; full legacy cell payload is not duplicated. Any durable minimal view is measured and counted, never assumed zero.

| Bundle estimate | Low GiB | Point GiB | High GiB | Expected status |
|---|---:|---:|---:|---|
| 3,941 actual | 26.809451 | 28.761580 | 30.813710 | estimated envelope below target; no production pass |
| 5,210 normalized | 35.442081 | 38.022795 | 40.735709 | estimated envelope below target; no production pass |

### Scenario B — `MIGRATION_PHYSICAL_COMPATIBILITY_TERMINAL`

At least one physical consumer remains; compatibility terminal is mandatory and counted. Current legacy terminal bytes are the conservative input until the final format is measured.

| Bundle estimate | Low GiB | Point GiB | High GiB | Expected status |
|---|---:|---:|---:|---|
| 3,941 actual | 30.263311 | 32.215440 | 34.267570 | estimated envelope below target; no production pass |
| 5,210 normalized | 40.008082 | 42.588796 | 45.301710 | point below target; high enters 45–50 warning; no production pass |

The production actual/normalized gate has not run. `TARGET_GATE_EXPECTED: YES` is prohibited.

Workspace names and formulas are identical to the capacity contract:

```text
REQUIRED_FREE_BYTES
  = 1.25
    * (PROJECTED_FINAL_DURABLE_BYTES
       + PROJECTED_TEMPORARY_PEAK_BYTES)

WORKSPACE_REQUIRED_BYTES
  = EXISTING_WORKSPACE_OCCUPIED_BYTES
    + REQUIRED_FREE_BYTES
```

Existing occupancy is not new-bundle capacity, is added once, and is not multiplied by 1.25. Temporary peak is not final durable bytes. Workspace and 45/50 GiB bundle gates are independent. Example: existing 100 GiB, final 30 GiB, temporary 10 GiB gives required free 50 GiB and workspace required 150 GiB, with no double count.

`PROJECTED_TEMPORARY_PEAK_BYTES` is unmeasured. Scenario A and B therefore use their respective projected final values in the formulas but make no numeric production workspace claim. Phase 6 measures temporary peak and real existing occupancy before full market.

| Scenario | Required-free range GiB | Workspace-required range GiB |
|---|---|---|
| A | `1.25 * ((26.809451..30.813710) + PROJECTED_TEMPORARY_PEAK_GIB)`; point uses `28.761580` | `EXISTING_WORKSPACE_OCCUPIED_GIB + scenario_A_required_free_gib` |
| B | `1.25 * ((30.263311..34.267570) + PROJECTED_TEMPORARY_PEAK_GIB)`; point uses `32.215440` | `EXISTING_WORKSPACE_OCCUPIED_GIB + scenario_B_required_free_gib` |

This is the complete current workspace result: the scenario-dependent final durable term is recalculated, while the unmeasured temporary term remains explicitly blocking rather than filled with zero.

## 9. Implementation phases and gates

Each phase is independently reviewable. No phase mutates old immutable artifacts in place.

| Phase | Inputs | Allowed files | Output artifact | Exact gate | Dependency gate | Terminal gate | Capacity gate | Rollback boundary | Next-phase condition |
|---|---|---|---|---|---|---|---|---|---|
| 0. Contract freeze | protected prototype evidence; read-only code audit | only this RFC and capacity doc/JSON | no production artifact | cross-file decisions/arithmetic consistent | future schema/enforcement assigned | completeness/migration policy frozen | 45/50, scenarios, formulas frozen | remove only three untracked candidates before commit | independent rereview only; this task stops |
| 1. Pure types/manifest/codec/index | reviewed Phase 0 | new contract, checkpoint codec, journal codec, index modules and focused tests only | synthetic temp fixtures | binary64/state/tracker/lifecycle/terminal round trip; malformed input fails | `DependencyBinding` and replay parameter schemas/validators only; no activation | terminal completeness schema covers matrix | exact file accounting only; no market claim | revert Phase 1 commit; registry/builder unchanged | pure tests and independent review pass |
| 2. Three-symbol writer | Phase 1 types; registered frozen inputs; independent legacy oracle | new writer entry and narrow shared-stream extraction; focused tests | unregistered 3-symbol checkpoint/journal/feature candidate | every day/model/state/feature/identity/share/mass bit exact, all seller models | dependency refs/digests validate; no pin activation | terminal completeness round-trip exact | physical bytes/overrides reported; no extrapolated pass | delete unregistered output and revert phase | zero mismatch and complete terminal proof |
| 3. Reader/resolver adapter | Phase 2 candidate and oracle | new resolver/factory and narrow lifecycle consumer adapters; focused tests | unregistered replay reports | checkpoint/month/year/lifecycle exact; mixed/mismatch fails | dependency digest and parameter-manifest validation | versioned checkpoint terminal adapter exact | reader/index adds no hidden bytes | explicit config selects old resolver | zero exact mismatch and fail-closed matrix pass |
| 4. Production integration before sample gate | reviewed Phase 3 | shared stream, feature consolidation, registry/loader retention implementation, physical consumer adapters/tests | 3-symbol annual-shaped feature plus retention/terminal integration evidence | one transition feeds both sinks; feature/peak/PIT exact | pin/lease, reverse refs, deletion order, GC protection implemented/tested | all physical consumers migrated or counted versioned output produced | feature, metadata, compatibility bytes reported | old builder/registry path explicitly selected; revert isolated commits | retention enforcement and terminal release prerequisites pass |
| 5. Fixed 50-symbol production-equivalent gate | Phase 4 integrated path; fixed sample | validation harness/config only; no semantic change | immutable validation-only candidate/evidence | full matrix zero mismatch | retention enforcement already active in test registry; bindings pinned | sample terminal policy matches declared scenario | actual sample distribution and estimates; estimates do not pass production | discard candidate; old production remains | exact gates pass and estimated envelope reviewed; not registration |
| 6. Capacity/RSS/resume/failure injection | Phase 5 evidence | instrumentation and isolated optimizations only | capacity/runtime/RSS/temp/workspace/failure report | resume digest equals clean; corruption fails closed | missing/digest/delete/GC/interruption/stale-pin/orphan and reverse-reference corruption tests pass and fail closed; corrupt reverse index blocks GC and delete until explicit repair/rebuild and validation | compatibility/mixed/partial terminal failures pass | temporary peak measured; workspace computable; scenario rerun | revert instrumentation/optimization; discard output | all failure and preflight gates pass |
| 7. Full-market build | reviewed Phase 6 versions and pinned inputs | no semantic code change during run | complete unregistered full-market candidate | complete universe/models; zero exact/conservation errors | all dependencies pinned and reverse-verified | declared terminal scenario physically complete | final `ACTUAL` and normalized gates; both <=45 target, either >50 fail | candidate remains unregistered; old selection intact | independent review of actual files and gates |
| 8. Panel/consumers/new RC | reviewed Phase 7 candidate | registry/config bindings, panel/resolver consumer wiring, release metadata/tests | registered bundle/feature, rebuilt panel, new RC | panel/PIT/schema/replay/strategy/lifecycle exact; no fallback | production registry binding and retention remain enforced | physical consumers exact; compatibility may stop only after release gate | recount registered bundle and attach dependency/temp/workspace reports | repoint explicit registry/config to old immutable V12 | RC only after independent release review |

Phase count remains 9 (`0` through `8`). Full market is Phase 7 only after Phase 6. Panel rebuild is Phase 8 only after Phase 7. Retention and terminal prerequisites are required before Phase 5.

## 10. Exact and failure regression matrix

Required cases are three seller models; initialization/warmup; ordinary aging; zero turnover; suspension; split/reverse split; cash dividend; share multiplier; float addition/removal; destination collision; multi-arc; opening/month/year checkpoint boundaries; exact terminal round trip; lifecycle and temporal continuation; missing dependency; digest mismatch; replay parameter mismatch; premature dependency delete; GC while active; bundle delete then pin release; interrupted delete; stale pin; orphan reference; reverse-reference corruption; resume; partial/duplicate shard; mixed-version root; feature/panel parity; and physical compatibility terminal presence/count/digest/version. Every numeric comparison uses bit equality or the existing exact contract; no relaxed tolerance is introduced.

The Phase 6 reverse-reference corruption failure matrix must inject and verify all six corruption classes defined in section 4 and must include: GC while the reverse index is corrupt; dependency deletion while the reverse index is corrupt; bundle deletion while forward and reverse bindings disagree; an interrupted reverse-index update; and recovery only after explicit registry repair or rebuild followed by successful validation. In every case dependency validation fails, dependency GC and dependency delete are blocked, bundle registration/read/delete never falls back, silent repair is forbidden, and operation remains fail closed. A corrupt reverse index is not evidence that no dependency exists.

## 11. Future modification scope from read-only audit

No file below is modified in Phase 0. Classification means likely scope, not permission to change semantics.

| File / area | Classification | Future reason and phase |
|---|---|---|
| `scripts/build_real_chip_year.py` | REQUIRED | Phase 2/4 shared stream, new writer, terminal adapter/output; avoid core transition changes |
| `src/cyq_game/strategy/chip_lineage.py` | REQUIRED | Phase 3 explicit resolver factory/facade; preserve legacy resolver |
| `src/cyq_game/chip/operator_index.py` | AVOID_IF_POSSIBLE | keep legacy-only; use new checkpoint/journal index module |
| `src/cyq_game/chip/daily_feature_fact.py` | CONDITIONAL | reuse/extract accumulator without duplicating transition; may use new module |
| `src/cyq_game/strategy/semantic_contract.py` | REQUIRED | declare new fingerprints and bump epoch only at activation |
| `src/cyq_game/chip/semantic_contract.py` | REVIEW_ONLY | path requested by review does not exist in the current tree; do not create a duplicate—the applicable implementation is `src/cyq_game/strategy/semantic_contract.py` |
| `src/cyq_game/data/registry.py` | REQUIRED | Phase 4 binding, pin/lease, reverse dependency, deletion/GC enforcement |
| `configs/data_asset_registry.json` and relevant input snapshot loader/configs | REQUIRED | Phase 4/8 schema/bindings after implementation; no Phase 0 change |
| `src/cyq_game/strategy/panel.py` | REQUIRED | Phase 8 feature manifest/PIT/bundle binding; confirm no payload read |
| `src/cyq_game/strategy/exact_replay.py` | REQUIRED | Phase 3/8 resolver factory and verified lineage identity |
| `scripts/freeze_current_chip_asset.py` | REQUIRED | Phase 4 checkpoint/compatibility inventory and terminal release policy |
| `scripts/assemble_real_chip_multiyear_root.py` | REQUIRED | Phase 4 versioned checkpoint/compatibility parity and atomic assembly |
| `scripts/merge_real_chip_year_roots.py` | REQUIRED | Phase 4 versioned physical inventory merge and counted terminal policy |
| terminal writer/reader (`TERMINAL_SCHEMA`, `_write_terminal_snapshots`, `_read_terminal_snapshots`) | REQUIRED | Phase 1 schema and Phase 2/4 exact adapter/export compatibility |
| new checkpoint/journal contract, codecs, index | REQUIRED | Phase 1 pure types and codecs |
| new checkpoint/journal resolver | REQUIRED | Phase 3 new reader implementation |
| `src/cyq_game/strategy/markup_retest.py` | REQUIRED | Phase 8 registered annual feature/lineage manifest binding |
| `src/cyq_game/strategy/signals.py`, `research.py` | CONDITIONAL | Phase 8 only if stable facade cannot preserve API |
| `semantic_chip.py`, `current_chip_features.py`, `exact_chip_features.py` | CONDITIONAL | explicit resolver routing for new bundle consumers |
| `scripts/reconstruct_chip_terminals_from_lineage.py` | REQUIRED | Phase 4 adapter/export migration or explicitly legacy-only replacement |
| `scripts/audit_v13_oracle_retention.py` | REVIEW_ONLY | protected historical evidence; Phase 6 may read it, not modify it |
| relevant targeted tests | REQUIRED | added with owning phase; legacy safety tests stay |
| protected prototype script/test/evidence | REVIEW_ONLY | historical evidence; production must not import or modify them |

## 12. Final decisions and Phase 0 stop

1. Shared registered dependencies are allowed only when immutable, snapshot/digest-bound, separately reported, and retention-enforced.
2. Current registry retention enforcement is absent; Phase 4 must implement it before Phase 5.
3. Replay hash includes an explicit canonical parameter manifest, dependency digests, code inventory, runtime inventory, and self digest; mismatch fails closed.
4. Year-end checkpoint is canonical terminal state, but physical compatibility remains mandatory and counted until every consumer migrates and passes exact tests.
5. Scenario A remains below target as an estimate. Scenario B's normalized high is 45.301710 GiB and enters warning. Neither is a production pass.
6. Old/new roots cannot mix, and journal/feature share one canonical compute stream.
7. This revision can only be sent to a separate independent rereview. It is not safe to commit and does not authorize Phase 1.
