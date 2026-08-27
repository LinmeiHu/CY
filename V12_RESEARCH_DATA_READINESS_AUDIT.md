# V12 Research Data Readiness Audit

Date: 2026-08-27

Baseline: `43c2f73f170ba292e54063d59bc322be9859be63`

Branch: `fix/v12-temporal-peak-artifact-contract`

Validated code commit: `b1fa05714f964bee520350b782c18d060a845241`

## Outcome

The production seller-model identity defect is confirmed and fixed at the
`EnsembleTemporalPeakTracker` boundary. A five-symbol production-path rebuild
passed manifest, hash, codec, reader, conservation, and resume-contract
validation, and its year-local tracker reported `57 / 1,215` non-null track IDs
and `46 / 1,215` strict-valid rows.

Those coverage values are **not production-valid evidence of canonical
temporal identity**. The production checkpoint/journal worker advances the
chip state over the governed 2018--2019 warm-up but instantiates and advances
the temporal tracker only on 2020 output days. A chronological diagnostic that
advanced the unchanged canonical tracker over the same warm-up changed all 57
non-null IDs and all 46 strict-valid rows to null/invalid. This is a confirmed
tracker warm-up/continuation defect, not a reason to relax canonical ambiguity,
split, merge, loss, or reattachment rules.

The old 2020 V3 temporal-peak artifacts must be rebuilt. Both the semantic and
artifact-contract fingerprints changed, and the resume validator returns
`STALE` for either old fingerprint.

`UNKNOWN_COST_PRESENT` is not a confirmed defect. It is the deliberate
fail-closed representation of missing pre-2018 acquisition history and decays
only through modeled real sales. The tested 2020 annual build remains
research-valid but not strictly PIT-valid.

A 500-symbol rebuild is not safe. The immediate blocker is the confirmed
temporal-tracker warm-up/continuation defect. Separately, the repository can
replay accepted lifecycle and legal execution deterministically, but the
frozen V12 artifact does not bind one authoritative per-decision audit record
containing all rejected gates, frozen breakout/retest values, and execution
attempts.

## Confirmed defects and remediation

1. **Seller-model identity mismatch.** Production operator rows serialize
   `SellerModel.value` as `UNIFORM`, `DISPOSITION`, and `ACTIVE_STICKY`, while
   both V12 feature builders initialized the temporal tracker with lowercase
   strings. Exact key-set comparison therefore emitted
   `ENSEMBLE_SELLER_MODEL_MISSING` for every row.
2. **Temporal observability fields were dropped.** `TrackedPeak` calculated
   age, mass, and prominence, but `FACT_SCHEMA` did not persist them. The
   checkpoint adapter consequently wrote `age=0`, `prominence=0`, and used
   dominant-band mass instead of tracked-peak mass.
3. **The artifact contract did not bind the daily-feature schema.** The
   physical feature file was hashed, but `_artifact_contract_fingerprint()`
   did not name or enumerate `FACT_SCHEMA`.

The minimal fix:

- canonicalizes enum and lowercase/uppercase serialized identities once at
  `EnsembleTemporalPeakTracker` entry/update;
- rejects unknown, duplicate, or incomplete model sets without weakening the
  exact three-model ensemble requirement;
- preserves the established lexical anchor-model ordering and all peak
  matching/split/merge/lost semantics;
- persists `peak_track_age`, `peak_track_mass`, and
  `peak_track_prominence`;
- writes those exact values into the existing checkpoint continuation fields;
- versions and fingerprints the daily-feature schema.

No seller-model economics, strategy thresholds, PIT timing, execution timing,
corporate-action rules, chip migration, peak matching, or root-anchor formulas
changed.

## Confirmed unresolved blocker: tracker history starts too late

`_checkpoint_journal_symbol_worker` creates a fresh
`EnsembleTemporalPeakTracker`, then updates it only from `consume_day`.
`_run_symbol` calls that sink only when `fact.target_required` is true, so the
chip inventories receive the 2018--2019 warm-up while the temporal tracker does
not. Although the checkpoint schema can decode tracker continuation, the
current adapter persists only the ensemble tracked base, leaves all
seller-local scopes and applied action IDs empty, and has no production restore
path that reconstructs the complete ensemble tracker.

This violates the frozen V12 semantic-correctness requirement for
temporal-tracker continuation. The physical bundle remains hash-valid, but its
track IDs begin at an output-year boundary rather than at the governed causal
history boundary.

## Files changed

- `src/cyq_game/chip/peaks.py`
- `src/cyq_game/chip/daily_feature_fact.py`
- `src/cyq_game/chip/checkpoint_journal_writer.py`
- `src/cyq_game/strategy/semantic_contract.py`
- `scripts/build_real_chip_year.py`
- focused tests in `tests/test_daily_feature_fact.py`,
  `tests/test_chip_peak_equivalence.py`,
  `tests/test_checkpoint_journal_writer.py`,
  `tests/test_real_chip_storage.py`, and `tests/test_semantic_contract.py`

## Schema, fingerprints, and invalidation

| Contract | Before | After | Result |
|---|---|---|---|
| Feature schema | `chip-features-v6-temporal-canonical-peak` | `chip-features-v7-temporal-peak-observability` | changed |
| Daily fact schema | implicit | `v12-daily-feature-fact-v4-temporal-peak-observability` | explicit |
| Semantic fingerprint | `ff9a2a6bbd2d7273437a37e71a2e9725ad9a6bc8d13971a41e36f965b059811e` | `424e82a0dd817a8d2c1e618d2929aa58506d8b4336c6c765bf08692adf593518` | changed |
| Artifact contract | `v12-phase7-artifact-contract-v3` | `v12-phase7-artifact-contract-v4` | changed |
| Artifact fingerprint | `c22724a392b3bc9a5a6d38569c144aa3d4514c776e7cdb84237fab914bc0c0b9` | `58c18585f25b48c07467880d7c6d5a8eba6d8c49d003ae6c9142f91283adca62` | changed |
| Physical-policy fingerprint | `8bd117dd0a156592cbdc5628cf990278d56b28426c8f9311b8c9c7497eed720a` | same | encoding policy unchanged; file SHA values change |
| Checkpoint/journal schema | `chip-checkpoint-journal-schema-v1` | same | no structural codec change |
| Resume contract | `v12-phase7-resume-contract-v2` | same | comparison mechanism unchanged |
| Symbol shard manifest | `v12-phase7-symbol-shard-manifest-v2` | same | JSON shape unchanged |

Every rebuilt symbol returns `VALID` with the new fingerprints and `STALE`
when either old fingerprint is supplied. Existing 2020 V3 shards therefore
cannot be silently reused and must be rebuilt from governed inputs. No
compatibility path treats all-missing temporal peaks as valid.

## Unknown-cost diagnosis

1. **Origin:** the first staged 2018 snapshot is initialized entirely as
   unknown cost because no pre-2018 acquisition history is registered.
2. **Economic expectation:** yes. Fabricating a cost band would violate PIT and
   input-governance contracts.
3. **Decay:** each seller model removes unknown lots through the same real
   daily seller allocation used for other lots; same-day purchases are known
   cost and cannot be resold. Unknown mass can disappear after complete churn
   or fall below strict tolerance, but sticky/hazard tails may persist.
4. **One-year 2020 result:** `UNKNOWN_COST_PRESENT` on every tested row is
   consistent with the two-year warmup and observed seller-model tails. It is
   not a count of invalid research rows.
5. **Warmup:** missing pre-2018 history is the root source. More governed prior
   history would reduce initialization uncertainty.
6. **Checkpoint initialization:** checkpoints do not invent unknown mass.
   Terminal/checkpoint rows preserve null cost coordinates, shares, and
   `initialization_prior_units` exactly; resume restores them exactly.
7. **Defect:** none demonstrated. Existing tests also prove that full real
   turnover can replace all unknown cost and make known-cost mass complete.
8. **`hard_valid`:** not hardcoded unreachable. It becomes true only when
   unknown mass is within tolerance and all other inputs are strict-valid. It
   is empirically zero under the tested 2020 annual contract; `research_valid`
   deliberately permits only the governed recoverable reason codes.

Corporate actions preserve the diagnosis: cash actions do not alter unknown
coordinates; splits scale shares and free float together; explicit removals
reduce the selected source lots and their initialization-prior units; unknown
float additions remain explicit. Seller behavior and conservation are
unchanged.

## Temporal peak availability

| Field | Before | After | Lifecycle role |
|---|---|---|---|
| `peak_track_id` | persisted but null on production rows due to defect | persisted correctly | required identity |
| `tracked_base_peak` | persisted but null due to defect | persisted correctly | diagnostic center |
| `peak_track_age` | calculated, dropped | persisted | persistence research |
| band lower/upper | persisted but null due to defect | persisted correctly | required anchor band |
| `peak_track_mass` | calculated, dropped | persisted | research; exact checkpoint value |
| `peak_track_prominence` | calculated, dropped | persisted | research; exact checkpoint value |
| split/merge/ambiguous/lost | persisted as ensemble-day flags | unchanged | panel validity gates |
| peak definition/track versions | persisted | unchanged | required contract gates |

Mass and prominence were not missing from peak detection or profile metrics;
they were lost only in daily projection. Current production lifecycle rules do
not gate on age, mass, or prominence, so materializing them changes
observability rather than strategy decisions.

The checkpoint contract has fields for tracker continuation, but the current
adapter still records only the ensemble tracked base; seller-local scopes and
applied action IDs are empty, and no production restore path reconstructs an
`EnsembleTemporalPeakTracker` from that continuation. The five-symbol
diagnostic below proves that this materially changes within-2020 IDs and
validity. It is an unresolved semantic blocker.

## Low temporal-peak coverage classification

Strict-valid is evaluated without relaxation as:

```text
peak_track_id is not null
and tracked_base_peak is not null
and not peak_track_ambiguous
and not peak_track_split
and not peak_track_merge
and not peak_track_lost
and peak_definition_version == canonical-chip-peak-v2
and peak_track_version == temporal-chip-peak-v2
```

### Persisted `peak_track_state` counts

| Symbol | `ENSEMBLE_PEAK_AMBIGUOUS` | `TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS` | `TRACKED` | Total |
|---|---:|---:|---:|---:|
| `000001.SZ` | 152 | 91 | 0 | 243 |
| `002260.SZ` | 243 | 0 | 0 | 243 |
| `002706.SZ` | 154 | 81 | 8 | 243 |
| `300604.SZ` | 135 | 102 | 6 | 243 |
| `600519.SH` | 200 | 0 | 43 | 243 |
| **Aggregate** | **884** | **274** | **57** | **1,215** |

No row has `ENSEMBLE_SELLER_MODEL_MISSING`, `PEAK_MISSING`,
`DOMINANT_PEAK_AMBIGUOUS`, `LOST`, or another persisted state. This confirms
that the original seller-model key defect is absent from the rebuilt sample.

### Raw strict-invalid predicates (overlapping)

These are direct predicate counts. They intentionally overlap: projection
sets `peak_track_ambiguous=true` whenever the tracked base is absent, so every
one of the 1,158 null-ID rows is simultaneously `no track`, `ambiguous`, and
`missing base`. Split/merge/lost are ensemble-day event flags over all tracked
peaks and can overlap those three conditions.

| Symbol | Strict invalid | No track | Ambiguous | Split | Merge | Lost | Missing base | Version mismatch | Other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `000001.SZ` | 243 | 243 | 243 | 19 | 25 | 29 | 243 | 0 | 0 |
| `002260.SZ` | 243 | 243 | 243 | 0 | 0 | 0 | 243 | 0 | 0 |
| `002706.SZ` | 235 | 235 | 235 | 13 | 20 | 33 | 235 | 0 | 0 |
| `300604.SZ` | 241 | 237 | 237 | 25 | 37 | 63 | 237 | 0 | 0 |
| `600519.SH` | 207 | 200 | 200 | 9 | 12 | 13 | 200 | 0 | 0 |
| **Aggregate** | **1,169** | **1,158** | **1,158** | **66** | **94** | **138** | **1,158** | **0** | **0** |

### Exclusive first-failure attribution

For a total-preserving attribution, the frozen diagnostic priority is: no
track, ambiguous, split, merge, lost, missing base, version mismatch, other.
Ambiguous and missing-base receive zero exclusive rows because both always
co-occur with the earlier no-track predicate; their raw counts above remain
the authoritative field-level counts.

| Symbol | No track | Ambiguous | Split | Merge | Lost | Missing base | Version mismatch | Other | Total invalid |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `000001.SZ` | 243 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 243 |
| `002260.SZ` | 243 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 243 |
| `002706.SZ` | 235 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 235 |
| `300604.SZ` | 237 | 0 | 2 | 0 | 2 | 0 | 0 | 0 | 241 |
| `600519.SH` | 200 | 0 | 6 | 1 | 0 | 0 | 0 | 0 | 207 |
| **Aggregate** | **1,158** | **0** | **8** | **1** | **2** | **0** | **0** | **0** | **1,169** |

Thus the exact gap between 57 non-null IDs and 46 strict-valid rows is 11:
eight first fail on split, one on merge, and two on lost. There are no version
mismatches and no unclassified invalid rows.

### Canonical full-history diagnostic

The diagnostic replay used the same registered daily/minute/corporate-action
inputs, chronological order, chip migration, seller models, canonical peak
candidates, versions, and tracker matching rules. Its only change was to
advance the tracker on every replayable transition from the governed warm-up
instead of beginning on 2020 output days. It wrote no artifact.

| Symbol | Warmed `ENSEMBLE_PEAK_AMBIGUOUS` | Warmed `TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS` | Warmed `TRACKED` | Non-null ID | Strict valid |
|---|---:|---:|---:|---:|---:|
| `000001.SZ` | 152 | 91 | 0 | 0 | 0 |
| `002260.SZ` | 243 | 0 | 0 | 0 | 0 |
| `002706.SZ` | 154 | 89 | 0 | 0 | 0 |
| `300604.SZ` | 135 | 108 | 0 | 0 | 0 |
| `600519.SH` | 200 | 43 | 0 | 0 | 0 |
| **Aggregate** | **884** | **331** | **0** | **0** | **0** |

The 884 ensemble-ambiguity rows are unchanged, so their low coverage is an
expected consequence of the canonical exact three-model, one-to-one consensus
rule. The year-local run's first differences occur exactly when it reports a
newly tracked output-year base: `002706.SZ` on 2020-01-02,
`600519.SH` on 2020-01-03, and `300604.SZ` on 2020-01-14. With causal warm-up,
the pre-existing base has already been lost or made ambiguous; canonical
semantics correctly do not reattach a later look-alike or reset the base at the
year boundary.

**Conclusion:** the individual ambiguity, split, merge, and loss outcomes are
consistent with canonical tracker semantics, but the reported `57 / 1,215`
non-null IDs and `46 / 1,215` strict-valid rows are evidence of another defect:
the artifact starts tracker identity at the target-year boundary. They must not
be used to justify the 500-symbol rebuild.

## Lifecycle recoverability

Classification: **A** persisted; **B** exactly derivable by deterministic
replay; **C** computed transiently and not serialized; **D** not recoverable
from the V12 shard alone.

| Quantity | Class | Authority |
|---|---|---|
| exact accumulation/setup score and component evidence | A in `panel_signal_scan`; D in V12 shard alone | causal SQL in `strategy/panel.py` |
| breakout timestamp | A for state transitions/signals; B otherwise | `LifecycleMachine.advance` |
| breakout support, frozen ATR, volume, turnover | C; B from frozen panel replay | `LifecycleMemory` at BREAKOUT transition |
| pre-breakout average cost and p50 | C; B from frozen panel replay | `LifecycleMemory` |
| retest timestamp | A for qualified signals; B for candidate days | signal/event stream plus replay |
| exact retest depth, cost migration, volume ratio, turnover ratio | C; B from frozen panel replay | `_retest_qualified` |
| immutable root-anchor identity/band/reference mass | A for qualified signals; B for open/rejected lifecycles | `freeze_lifecycle_anchor` |
| `exact_anchor_retention` central/lower/upper/model values | A for qualified signals; B with exact lineage replay; D in feature shard alone | `exact_anchor_retention` and lineage resolver |
| seller-model disagreement gate | A in exact-replay qualified records; C for rejected days; B from panel | `observation_from_record` |
| lifecycle transitions | A when state changes; B for unchanged/rejected days | signal event stream and lifecycle replay |

For accepted parameter `9baed76ec299161c`, the authoritative parameter set
is setup `1.00`, breakout `0.25 ATR`, retest depth `0.50 ATR`, cost migration
`0.50 ATR`, distribution `0.80`, and protective stop `1.50 ATR`. Fixed config
values are retest volume/turnover ratios `0.80`, root retention lower bound
`0.70`, and model disagreement at most `3.00 ATR`. The exact retest formulas
use the frozen breakout ATR/support/volume/turnover and pre-breakout continuous
average-cost/p50 values; generic daily deltas are not authoritative substitutes.

## Production entry-ledger availability

No single authoritative per-decision entry ledger currently exists.

- Signal Parquets persist qualified signal ID, parameter ID, lifecycle state,
  accumulation/breakout/retest dates, immutable root anchor, and exact
  retention values.
- Lifecycle event Parquets persist state changes, signal creation, exit intent,
  and soft-exit cancellation, but not unchanged/rejected gates.
- Exact replay persists entry status, fill timestamp, fill price, quantity,
  total cash, and aggregate reason codes.
- `EntryExecution.attempts` contains legal-window attempts in memory, but those
  attempts are not serialized in the signal record.
- `TrialLedger` is an append-only experiment/governance ledger, not a
  per-symbol production decision ledger.

The smallest deterministic audit ledger should be one row per
`(symbol, decision_at, parameter_id)` and bind the panel snapshot, lineage
snapshot, parameter manifest, and execution-window snapshots. It should record
observed lifecycle state; frozen breakout fields; exact retest quantities;
root-anchor identity and retention interval; ordered gate results; first and
all failed gates; qualified/rejected status; signal and intent IDs; every legal
execution attempt; terminal execution status, time, and price. It should be
written from the existing lifecycle and execution engines, not from a second
strategy implementation, and covered by a manifest/content hash.

## Tests and validation

- Reproduce-first production-path test failed before the fix with null
  `peak_track_id`, then passed after the boundary fix.
- Required coverage includes valid three-model ensemble, case-compatible enum
  serialization, unknown/missing/duplicate models, deterministic output,
  Parquet round trip, and checkpoint round trip of age/mass/prominence.
- Focused test run: `29 passed`.
- Broader directly related run: `110 passed`; seven fixture-dependent tests
  could not start because this dedicated worktree has no historical
  `data/validation/v12_checkpoint_journal_phase2_3symbol` fixture. The new
  bundle independently passed the production reader and activation paths.
- Focused Ruff checks and `git diff --check`: pass.

## Five-symbol rebuild (physical integrity and year-local observations)

Activated bundle:
`/Users/linmei/Documents/CY/data/validation/v12_temporal_peak_fix_5symbol_20260827`

| Symbol | Rows / coverage | Strict peak valid | Non-null ID / unique | Age min/median/p90/max | Mass/prominence | Unknown | hard/research valid |
|---|---|---:|---:|---|---:|---:|---:|
| `000001.SZ` | 243, 2020-01-02..2020-12-31 | 0 (0.00%) | 0 / 0 | n/a | 0 / 0 | 243 | 0 / 243 |
| `002260.SZ` | 243, 2020-01-02..2020-12-31 | 0 (0.00%) | 0 / 0 | n/a | 0 / 0 | 243 | 0 / 243 |
| `002706.SZ` | 243, 2020-01-02..2020-12-31 | 8 (3.29%) | 8 / 1 | 1 / 4.5 / 7.3 / 8 | 8 / 8 | 243 | 0 / 243 |
| `300604.SZ` | 243, 2020-01-02..2020-12-31 | 2 (0.82%) | 6 / 1 | 9 / 15 / 17.5 / 18 | 6 / 6 | 243 | 0 / 243 |
| `600519.SH` | 243, 2020-01-02..2020-12-31 | 36 (14.81%) | 43 / 1 | 2 / 31 / 48.8 / 53 | 43 / 43 | 243 | 0 / 243 |

Year-local totals: 1,215 rows; 46 strict peak-valid rows (3.79%); 57
non-null track-ID rows; age, mass, and prominence available on all 57; 1,215
`UNKNOWN_COST_PRESENT`; `hard_valid=0`; `research_valid=1,215`. The low-coverage
classification above supersedes these 57/46 values for semantic readiness:
under canonical full-history replay both counts are zero.

Integrity results:

- manifest-last candidate write and atomic directory activation: pass;
- 130 manifest-bound parts, 60 reader index rows: pass;
- exact size/SHA-256, checkpoint decode, journal decode, and Parquet open: pass;
- production reader construction: pass;
- current resume status for all five symbols: `VALID`;
- old semantic/artifact fingerprints for all five symbols: `STALE`;
- conservation maximum error: `0.0`;
- same-day resale maximum: `0.0`;
- root manifest SHA-256:
  `442d49a7d085f3f21dc252c0a088842f809d0578a02fbfe00d419f5ef6b15a58`.

The first activation with a redundant, reader-incompatible informational
manifest key was quarantined and moved to Trash. It is recoverable there; only
the reader-compatible bundle above remains in the validation directory.

## Required hard gates

`SELLER_MODEL_ROOT_CAUSE_CONFIRMED: YES`

`TEMPORAL_PEAK_FIX_REGRESSION_TESTED: YES`

`OLD_TEMPORAL_PEAK_ARTIFACTS_INVALIDATED_IF_REQUIRED: YES`

`UNKNOWN_COST_ROOT_CAUSE_CLASSIFIED: YES`

`UNKNOWN_COST_IS_CONFIRMED_BUG: NO`

`TEMPORAL_PEAK_MATERIALIZATION_COMPLETE: YES`

`LIFECYCLE_RECOVERABILITY_CLASSIFIED: YES`

`ENTRY_LEDGER_RECOVERABILITY_CLASSIFIED: YES`

`PRODUCTION_STRATEGY_SEMANTICS_CHANGED: NO`

`SMALL_REBUILD_EXACT_INTEGRITY_VALID: YES`

`SMALL_REBUILD_TEMPORAL_PEAK_VALIDITY_NONZERO: YES`

`LOW_TEMPORAL_PEAK_COVERAGE_CLASSIFIED: YES`

`TEMPORAL_TRACKER_WARMUP_CONTINUATION_EXACT: NO`

`SMALL_REBUILD_CANONICAL_HISTORY_COVERAGE_VALID: NO`

`SAFE_TO_REBUILD_500_FOR_RESEARCH: NO`

## Exact next step

First, make temporal-tracker history exact without changing canonical validity:
either advance the complete ensemble tracker over every governed warm-up day or
restore a complete checkpoint continuation containing all seller-local and
ensemble scopes, previous peaks, base IDs, and applied action IDs. Add a
single-pass-versus-year-boundary-resume regression that requires bit-exact
tracker states and feature rows. Then rebuild this five-symbol sample and
reclassify coverage.

Separately, add and regression-test the deterministic lifecycle/entry audit
ledger described above, binding it to the frozen panel, lineage, parameter,
and execution-window snapshots. Prove exact replay and ledger hashes before
reconsidering a 500-symbol research rebuild. Do not reset a lost base, reattach
a look-alike, weaken ambiguity/split/merge/lost/version gates, change strategy
thresholds, or start the 500-symbol rebuild before both blockers are closed.
