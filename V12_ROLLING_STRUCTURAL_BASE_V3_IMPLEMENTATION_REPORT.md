# V12 Rolling Structural Base V3 Implementation Report

Date: 2026-08-27  
Branch: `impl/v12-rolling-structural-base-v3`  
Production implementation commit: `a43899e9e2218b641b63c122ac8f078fbc365656`

The supplied design-commit token was the unresolved placeholder
`<V3_DESIGN_COMMIT>`. The named design and implementation branches both started
at `e063c338e4`; the authoritative
`V12_ROLLING_STRUCTURAL_BASE_V3_DESIGN.md` and its read-only reference/specification
artifacts were read from the isolated design worktree. No reference code was used
to generate the production artifacts.

## 1. Files changed

Production implementation:

- `src/cyq_game/chip/peaks.py`
- `src/cyq_game/chip/peak_versions.py`
- `src/cyq_game/chip/checkpoint_journal_contract.py`
- `src/cyq_game/chip/checkpoint_journal_writer.py`
- `src/cyq_game/chip/daily_feature_fact.py`
- `src/cyq_game/strategy/semantic_contract.py`
- `scripts/build_real_chip_year.py`
- `scripts/prototype_checkpoint_journal_writer_3symbol.py`
- `scripts/build_v12_rolling_structural_base_v3_5symbol.py`

Tests:

- `tests/test_rolling_structural_base_v3_production.py`
- `tests/test_temporal_peak_lifecycle_audit.py`
- `tests/test_chip_peak_equivalence.py`
- `tests/test_real_chip_storage.py`
- `tests/test_checkpoint_journal_contract.py`
- `tests/test_checkpoint_journal_writer.py`

Deliverable:

- `V12_ROLLING_STRUCTURAL_BASE_V3_IMPLEMENTATION_REPORT.md`

## 2. Exact V3 production implementation

The focused production regression first reproduced V2's failure: after A reached
terminal loss, a persistent, independently born B existed but could not become
the rolling structural base because `_base_track_id` still held A's orphaned
tombstone. The regression failed on the untouched V2 production code before the
production edit.

The minimal V3 transition is implemented in `TemporalPeakTracker.update`:

1. The binding present at the start of the observation is captured.
2. Matching, split/merge/ambiguity evaluation, terminal-loss emission, and the
   current observation result retain the established fail-closed behavior.
3. If the bound identity is terminally lost, the live binding becomes unbound
   after that loss observation.
4. Lost peaks are not placed back in `_previous`; they cannot participate in a
   future match.
5. A later live track can bind only through the unchanged initial-binding guard.
6. Track IDs remain independently derived from version, symbol, scope/model,
   birth date, and birth buckets. A later B therefore cannot reuse A's identity.

The V3 transition supports repeated `A -> lost -> B -> lost -> C` episodes. It
does not relax canonical match tolerances, seller-model consensus, split, merge,
ambiguity, or lost-track rules. Loss-day observations remain fail-closed.

Terminal IDs do not need to remain as matchable checkpoint state: a terminal peak
is removed from the live matching set, future births have a later birth date in
their identity payload, and restore rejects any continuation containing a
`lost` or `reappear` live peak. The five-symbol replay observed 657 births, 643
terminal identities, and zero reuse of a terminal identity.

Daily feature projection continues to persist the canonical tracked-base ID,
age, band, mass, prominence, split/merge/lost/ambiguous flags, state, track
version, and definition version. No tracked-base mass or prominence fallback was
introduced. On every non-null output row, tracked mass was read from the tracked
peak rather than substituted from the dominant-band scalar.

## 3. Year-boundary continuation fix

`_run_symbol` now treats warmup days as projection days when a day sink is
present. Before target-year output it advances, in order:

- chip state;
- canonical peak candidates;
- all temporal seller-model and ensemble trackers;
- rolling-base binding/state;
- checkpoint-journal transition state.

The sink consumes those transitions while row persistence and target-year row
counts remain suppressed. The tracker is not recreated on 2020-01-01.

The production-path regression compares continuous 2018-2020 execution with
2018/2019 suppressed-output warmup followed by 2020 output. The first 2020 B
observation retains age 2 in the test fixture, and the complete projected rows
and continuation state are exact. Calendar-year boundaries therefore have no
tracker semantics.

## 4. Root-anchor isolation evidence

The integration characterization freezes production `LifecycleAnchor` A, then
drives the rolling tracker through terminal loss and a legal rebind to B. The
result is:

- current rolling structural base: B;
- frozen strategy lifecycle root anchor: A.

No code in `exact_anchor_retention`, markup/retest lifecycle lineage, entry
lifecycle semantics, thresholds, or execution timing was changed.

## 5. Version, schema, and contract changes

| Binding | V3 value | Decision |
|---|---|---|
| Peak track | `temporal-chip-peak-v3` | Bumped: lifecycle identity/binding semantics changed. |
| Peak definition | `canonical-chip-peak-v2` | Unchanged: candidate detection semantics did not change. |
| Semantic epoch | `cyq-semantic-epoch-20260827-v4` | Bumped. |
| Feature schema | `chip-features-v8-rolling-structural-base-v3` | Bumped. |
| Daily feature fact | `v12-daily-feature-fact-v5-rolling-structural-base-v3` | Bumped. |
| Checkpoint schema | `chip-checkpoint-journal-schema-v2` | Bumped for exact tracker continuation. |
| Checkpoint artifact | `v12-chip-bundle-checkpoint-journal-v2` | Bumped. |
| Transition semantics | `real-chip-transition-semantics-v2` | Bumped. |
| Resume contract | `v12-phase7-resume-contract-v3` | Bumped. |
| Artifact contract | `v12-phase7-artifact-contract-v5` | Bumped. |
| Symbol shard manifest | `v12-phase7-symbol-shard-manifest-v3` | Bumped. |
| Physical contract | `v12-phase7-physical-contract-v2` | Unchanged: physical encoding did not change. |

The replay parameter binding for the tracker is now `peak-track-v3`.

## 6. Invalidation behavior

Every rebuilt symbol reports `VALID` under the current V3 semantic and artifact
fingerprints. Substitution of the old semantic fingerprint returns `STALE`, and
substitution of the old artifact fingerprint returns `STALE`, for all five
symbols. A serialized V2 tracker continuation is explicitly rejected as
incompatible. Restore also fails closed on stale definition/track versions,
missing or reordered scopes, duplicate live IDs, a non-live base binding,
non-positive age, noncanonical action IDs, or lost/reappear live state.

The five-symbol production contracts are:

- semantic fingerprint:
  `6a20b7be1b60f6c978bbe28b28816e47c4e7debcb2ba48458aa3f3a52d7cbf6f`
- artifact contract fingerprint:
  `447c2fb85485bbd0c38d12d0bed9930c97f31ff142af30342987d9db07387d7f`
- physical fingerprint:
  `ec87355d9f716cbe1f78600a4d1e955a99af9bf6c75970b57274e6c04920a571`
- replay parameter manifest digest:
  `cf71c5ae52119d4709aba71488f3c5127d3e5f61c3a543a42abcd62ef2179bfd`
- root manifest SHA-256:
  `1ae9e08bd46bb13118e4cc6c59f27ccf0069527888d97f91bfd6887379c16f3b`

Per-symbol manifest SHA-256:

| Symbol | Manifest SHA-256 |
|---|---|
| `000001.SZ` | `fb635f06e8159922e350c4bed090fe70ec75f51bc416816ecb1b1ec4454604dd` |
| `002260.SZ` | `99705295b8f18992671d8a16ad209ad9cbfb0dab072413e84abe27c350a003a3` |
| `002706.SZ` | `016ae9bfe6f03617dee7cc84cb43fc3134cc65552e7dcac7bbfd4c6046909e57` |
| `300604.SZ` | `32d6b256ecea735f575b8f08e9b52031c63003464d537dce207020d30ac98f5d` |
| `600519.SH` | `b63cc7be2bbdbccb002541f4f7e5b42515743b7f1f5a27fe3aa8e0ae93280d45` |

## 7. Checkpoint/resume equivalence

Production checkpoints now require the explicit temporal continuation rather
than reconstructing partial state from a daily feature. The continuation contains
exactly four ordered scopes: `uniform`, `disposition`, `active_sticky`, and
`ENSEMBLE`. Each scope persists:

- current base binding or unbound state;
- applied corporate-action IDs;
- every live peak ID and age;
- exact IEEE-754 band, center, mass, and prominence bits;
- ambiguity/split/merge state;
- definition and track versions.

The old feature-derived adapter remains only in the explicitly unregistered
legacy prototype fixture and is not a production authority.

Continuous execution and checkpoint-stop-restore execution are exact for track
IDs, episodes, flags, binding, ages, mass/prominence, versions, and corporate
action coordinates. The five production artifacts restore all four scopes with
the production reader. Live-base corporate actions retain the same economic
identity; an action between terminal A and later B does not resurrect A.

## 8. Targeted tests

The focused regression was demonstrated failing under V2 before the edit. After
the V3 patch, the directly related suite completed:

`155 passed in 1.81s`

It covers normal continuation; terminal loss; no resurrection; unrelated and
look-alike B birth; legal B binding; repeated A/B/C episodes; split, merge, and
ambiguity fail-closed paths; later recovery; unresolved legitimate ensemble
ambiguity; root-anchor isolation; live and between-episode corporate actions;
year-boundary invariance; exact checkpoint/resume including a corporate action;
seller-model enum normalization and invalid identity handling; V2 continuation
rejection; manifest-last/exact-integrity behavior; and all required persisted
fields.

Additional checks:

- changed-file `py_compile`: passed;
- `git diff --check`: passed;
- changed-file Ruff with the five pre-existing `build_real_chip_year.py`
  `F401/F841` findings excluded: passed.

The ignored Ruff findings are pre-existing unused imports/local state in the
large production builder and were not cleaned up as an unrelated refactor.

## 9. Broader tests

The practical broader run reported `41 passed, 12 failed, 22 errors`. No new V3
assertion discrepancy was found:

- `tests/test_semantic_contract.py`: `10 passed`.
- Nine checkpoint integration failures are caused by the absent generated
  `data/validation/v12_checkpoint_journal_phase2_3symbol` fixture in this
  isolated worktree (eight direct `FileNotFoundError` cases and one subprocess
  failure on the same missing source); two tests in that group passed.
- Two legacy recompute-prototype failures directly index lower-case private
  `_local` keys although production has used canonical seller-model enum-value
  keys since the starting commit. The production constructor is unchanged by
  V3, and the production checkpoint path is covered by the green targeted suite.
- The markup/retest group produced 22 setup errors and one failure because its
  worktree-relative configured data root does not equal the registry's canonical
  `/Users/linmei/Documents/CY/data/...` location. No markup/retest code or
  strategy semantics changed.

These are reported separately as missing environmental fixtures, a legacy
prototype/private-state assumption, and a worktree path binding—not accepted as
production semantic equivalence evidence.

## 10. Five-symbol production rebuild

Only the governed symbols `000001.SZ`, `002260.SZ`, `002706.SZ`, `300604.SZ`,
and `600519.SH` were rebuilt. No 500-symbol or full-market build was started.
The production builder used the full governed 2018-2020 history and emitted only
2020 output.

Output:
`/Users/linmei/Documents/CY/data/validation/v12_rolling_structural_base_v3_5symbol_20260827`

Validation summary:

- activation: `PASS`;
- symbols: 5;
- 2020 rows: 1,215 (`243` per symbol, `2020-01-02` through `2020-12-31`);
- seller-model rows: 3,645;
- exact mismatch count: 0;
- maximum chip-mass error: 0.0;
- maximum same-day resale: 0.0;
- coverage: 1.0;
- artifact bytes: 41,281,753;
- root parts: 130;
- implementation provenance: `a43899e9e2218b641b63c122ac8f078fbc365656`.

Candidate and activated roots passed full size, SHA-256, codec, Parquet, terminal
completeness, production-reader, four-scope restore, and reuse validation.
Symbol artifacts and manifests were written last, then the root was atomically
activated. The validation harness initially attempted one cross-symbol dependency
catalog even though dependency identities are symbol-scoped; the artifacts were
already fully verified and activated. The harness was corrected to validate one
reader/catalog per symbol, and the complete existing candidate and activated
roots then passed without artifact regeneration.

Full-history counters are shown as `all/2020` where applicable. `Current` is the
number of non-null 2020 rows, with distinct IDs in parentheses.

| Symbol | Rows | Born | Terminal | Episodes | Rebinds | Current | Strict | Ensemble ambiguous | Split | Merge | Lost | Mass | Prom. | Unknown | hard | research |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `000001.SZ` | 243 | 105 | 101 | 9 | 8 | 86 (2) | 316/76 | 350/152 | 53/19 | 70/25 | 83/29 | 86 | 86 | 243 | 0 | 243 |
| `002260.SZ` | 243 | 103 | 99 | 12 | 11 | 0 (0) | 65/0 | 527/243 | 41/0 | 58/0 | 66/0 | 0 | 0 | 243 | 0 | 243 |
| `002706.SZ` | 243 | 96 | 95 | 18 | 17 | 88 (5) | 377/81 | 300/154 | 45/13 | 62/20 | 83/33 | 88 | 88 | 243 | 0 | 243 |
| `300604.SZ` | 243 | 281 | 279 | 49 | 48 | 105 (10) | 169/78 | 463/135 | 110/25 | 162/37 | 209/63 | 105 | 105 | 243 | 0 | 243 |
| `600519.SH` | 243 | 72 | 69 | 9 | 8 | 43 (1) | 323/36 | 356/200 | 38/9 | 56/12 | 63/13 | 43 | 43 | 243 | 0 | 243 |
| **Aggregate** | **1,215** | **657** | **643** | **97** | **92** | **322 (18)** | **1,250/271** | **1,996/884** | **287/66** | **408/94** | **504/138** | **322** | **322** | **1,215** | **0** | **1,215** |

`002260.SZ` remains `0/243` strict-valid 2020 base days because all 243 output
days are legitimately ensemble-ambiguous. No rule was weakened to increase
coverage. Full-history base availability is 1,444 days, including 322 output-year
days; no-base counts are 2,201 full-history and 893 in 2020.

`LOST_ID_REUSE_COUNT = 0`.

## 11. Production versus approved reference

Production and the approved read-only reference were independently replayed over
the same governed inputs. The comparison required exact equality and found:

- all 97 rolling-base episode start-date sequences exact;
- all 643 terminal-loss event-date sequences exact;
- daily birth counts exact;
- every split/merge/lost/ambiguity event record exact;
- daily active-track age multisets exact;
- state entering 2020 exact for every symbol;
- all 1,215 persisted 2020 IDs, centers, ages, bands, masses, prominences,
  states, flags, and versions exact against the production replay;
- per-symbol and aggregate strict-valid/base/no-base coverage exact;
- zero terminal-ID reuse in both implementations.

Literal production and reference IDs differ because the required V2-to-V3 track
version bump changes the ID namespace. After normalizing that version namespace,
birth/loss topology and episode identity relationships are exact. This is the
expected deterministic difference, not a semantic discrepancy.

The state entering 2020 also matches the design: `000001.SZ` is
ambiguous/bound, `002260.SZ` is ambiguous/unbound, `002706.SZ` is tracked/bound,
`300604.SZ` is ambiguous/bound, and `600519.SH` is ambiguous/bound.

## 12. Unknown-cost status

`UNKNOWN_COST_PRESENT` was not changed. All 1,215 output rows retain the existing
fail-closed unknown-cost classification, so `hard_valid = 0` and
`research_valid = 1,215`. The 271 strict-valid count in this report is temporal
rolling-base strict validity, not an override of the independent `hard_valid`
contract.

## 13. Remaining limitations

- The design commit supplied in the request was a placeholder rather than a
  resolvable hash; provenance is therefore recorded against the shared branch
  start `e063c338e4` and the authoritative design-worktree artifacts.
- Generated legacy checkpoint fixtures are not present in this isolated
  worktree, so their broader integration suites cannot pass here without a
  separately governed fixture rebuild. Current V3 production artifacts and
  continuation paths pass exact validation.
- The independent readiness-audit blocker remains: no single authoritative
  per-decision lifecycle/entry audit ledger binds the panel, lineage, parameter,
  and execution-window snapshots. This task intentionally did not change
  strategy or execution semantics.
- The full 500-symbol and full-market performance/storage behavior was not tested
  because those builds were explicitly prohibited.

## 14. Exact next step

Add and regression-test the deterministic lifecycle/entry audit ledger described
by the readiness audit. Bind each `(symbol, decision_at, parameter_id)` record to
the frozen panel, lineage, parameter, and execution-window snapshots; prove exact
replay and ledger hashes. Only after that independent blocker is closed should a
separately authorized 500-symbol research rebuild be reconsidered. Do not merge
this branch or start that rebuild automatically.

## Hard gates

`V3_PRODUCTION_REBIND_IMPLEMENTED: YES`

`LOST_TRACK_RESURRECTION_ALLOWED: NO`

`LOST_ID_REUSE_COUNT: 0`

`ROOT_ANCHOR_ISOLATION_VERIFIED: YES`

`YEAR_BOUNDARY_CONTINUATION_FIXED: YES`

`YEAR_BOUNDARY_INVARIANCE_TESTED: YES`

`CHECKPOINT_RESUME_V3_EQUIVALENT: YES`

`SELLER_MODEL_IDENTITY_FIX_PRESERVED: YES`

`V3_PEAK_TRACK_VERSION_BUMPED: YES`

`OLD_V2_TEMPORAL_ARTIFACTS_INVALIDATED: YES`

`FIVE_SYMBOL_PRODUCTION_REBUILD_VALID: YES`

`PRODUCTION_V3_MATCHES_APPROVED_REFERENCE_SEMANTICS: YES`

`FIVE_SYMBOL_2020_STRICT_VALID_ROWS: 271`

`PRODUCTION_STRATEGY_SEMANTICS_CHANGED: NO`

`SAFE_TO_REBUILD_500_FOR_RESEARCH: NO`
