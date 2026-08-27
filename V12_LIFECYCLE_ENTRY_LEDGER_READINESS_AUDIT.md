# V12 Lifecycle / Entry / Exit Ledger Readiness Audit

## 1. Outcome and central decision

**Decision: the exact V3 production lifecycle, qualified entry, entry execution, exit lifecycle, and exit execution are deterministically reconstructible later from the authoritative V3 artifacts, retained registered inputs, manifests, parameter contract, and pinned code. The ledger does not have to be materialized inside the V3 chip build.**

The requested operational answer is therefore:

> **NO — rebuilding the 500-symbol V3 temporal dataset now does not create a later requirement to rebuild or rewrite those chip shards when the decision ledger is added.**

The correct ledger architecture is a **post-hoc replay artifact**: an append-only sibling dataset with its own schema, manifest, and fingerprint, referencing an immutable V3 root-manifest hash. It must not be inserted into the chip root manifest or used to change any chip fingerprint.

This conclusion is conditional on retaining the complete authoritative replay envelope listed in Section 8. The current chip feature rows by themselves are not a sufficient replay envelope. In particular, registered daily/minute/corporate-action/execution inputs, their input manifests, exact lineage operators or checkpoint/journal replay support, the market calendar, strategy parameters, and pinned code must remain available. Unknown or mismatched lineage must continue to fail closed.

Two implementation-readiness gaps were found, but neither is irrecoverable information loss and neither requires a chip-shard schema change:

1. The current panel-to-observation adapter substitutes zero for absent `structure_support`, `prior_average_cost`, and `prior_cost_p50`, while `LifecycleObservation` rejects nonpositive values before the lifecycle machine can fail closed. A ledger materializer must handle structurally non-actionable rows consistently without inventing values.
2. The checkpoint/journal lineage facade requires a real `ReplayBackend`; no production raw-input backend is currently wired. The existing compact operator lineage path is usable. If checkpoint/journal-only resolution is required, that backend must be implemented and verified before the ledger materializer selects it.

No ledger code, 500-symbol rebuild, full-market run, strategy-threshold change, or V3 semantic change was made in this audit.

## 2. Scope and evidence base

The audit was performed on:

- branch: `audit/v12-lifecycle-entry-ledger-readiness`
- validated report commit: `963f37b3e08b8c0ce38ea2c9c3a12ae77d903374`
- V3 implementation commit recorded by the validated report: `a43899e9e2218b641b63c122ac8f078fbc365656`
- V3 five-symbol bundle: `/Users/linmei/Documents/CY/data/validation/v12_rolling_structural_base_v3_5symbol_20260827`
- accepted parameter ID: `9baed76ec299161c`
- V3 root-manifest SHA-256: `1ae9e08bd46bb13118e4cc6c59f27ccf0069527888d97f91bfd6887379c16f3b`
- semantic fingerprint: `6a20b7be1b60f6c978bbe28b28816e47c4e7debcb2ba48458aa3f3a52d7cbf6f`
- artifact fingerprint: `447c2fb85485bbd0c38d12d0bed9930c97f31ff142af30342987d9db07387d7f`
- replay-parameter digest: `cf71c5ae52119d4709aba71488f3c5127d3e5f61c3a543a42abcd62ef2179bfd`

The authoritative implementation paths inspected were:

- `src/cyq_game/strategy/panel.py`
- `src/cyq_game/strategy/markup_retest.py`
- `src/cyq_game/strategy/signals.py`
- `src/cyq_game/strategy/execution.py`
- `src/cyq_game/strategy/exact_replay.py`
- `src/cyq_game/strategy/chip_lineage.py`
- `src/cyq_game/chip/checkpoint_journal_reader.py`
- `src/cyq_game/strategy/checkpoint_journal_resolver.py`
- the V3 root/symbol/input manifests, checkpoint/journal files, feature shards, and the governed `v12_rc1_2020_stage`

The V3 contract remains the validated one: temporal peak-track version `temporal-chip-peak-v3`, peak definition `canonical-chip-peak-v2`, semantic epoch `cyq-semantic-epoch-20260827-v4`, feature schema v8, daily fact v5, checkpoint schema v2, checkpoint artifact v2, transition v2, resume v3, artifact v5, and symbol manifest v3.

## 3. Replay classification

The classifications used below are:

- **A — persisted directly:** the exact value is present in an authoritative artifact.
- **B — deterministic state replay:** the exact value is recoverable by running the pinned state machine over authoritative ordered observations.
- **C — deterministic derived value:** the exact value is transient in production but is recoverable from immutable inputs and pinned code.
- **D — irrecoverably lost:** a required value existed transiently but cannot be reconstructed exactly.
- **E — not a production concept:** the proposed value is not defined by the production strategy and must not be fabricated.

No required production lifecycle or execution value was classified D. A generic, independently defined “retest detected” event is E: production defines a retest through evaluation of `_retest_qualified` inside the legal post-breakout window; the ledger should record that evaluation and every gate, not invent a new detector.

| Decision value | Primary class | Authoritative reconstruction |
|---|---:|---|
| Current V3 tracked peak ID, episode, band, mass, prominence, flags, state, versions | A | V3 daily feature shard |
| Causal panel observation and setup components | C | Registered daily/chip/action/market inputs through `panel.py` |
| Lifecycle state before/after each decision | B | Ordered `LifecycleMachine.advance` replay |
| Setup creation and frozen root anchor | B/C | Setup gates plus `freeze_lifecycle_anchor` |
| Breakout qualification and frozen support/ATR/volume/turnover/costs | B/C | Lifecycle memory at the exact breakout decision |
| Retest evaluation and every raw ratio/gate | C | Frozen breakout memory plus current authoritative observation |
| Exact root retention bounds | C; A on emitted signals | Exact lineage resolver; retained directly on qualified signal rows |
| Qualified strategy signal | B; A if signal artifact retained | Lifecycle replay or serialized signal |
| Formal authorization | B/A when its calibration/edge-card contract is retained | `authorize_signal`; distinct from qualification |
| Research event-study entry request | B | Exact replay requests execution for every qualified signal in research scope |
| Entry attempts and fill | C; final result A if exact-replay signal output retained | Registered ordered five-minute windows through `execute_entry` |
| Exit lifecycle intent | B; A when event artifact retained | Open-position machine replay |
| Exit attempts, fill, and tail loss | C; final result A if trade output retained | Registered ordered five-minute windows through `execute_exit` |

## 4. Exact lifecycle semantics and thresholds

The accepted parameter contract is:

| Parameter | Accepted value | Replay use |
|---|---:|---|
| Setup threshold | `1.00` | All five setup evidence components must be present |
| Breakout excess | `0.25 ATR` | Close over frozen/causal structural support |
| Retest depth | `0.50 ATR` | Absolute distance from frozen breakout support to current low |
| Cost migration | `0.50 ATR` | Minimum of average-cost and p50-cost migration |
| Distribution threshold | `0.80` | Exit lifecycle distribution score |
| Protective stop | `1.50 ATR` | Close below frozen support less current ATR multiple |

Fixed production gates additionally include:

- retest volume ratio `<= 0.80` of frozen breakout volume;
- retest turnover ratio `<= 0.80` of frozen breakout turnover;
- root-anchor retention lower bound `>= 0.70`;
- model disagreement `<= 3 ATR`;
- market state in `RISK_ON` or `NEUTRAL`;
- sector state in `STRONG` or `NEUTRAL`;
- structure continuity and exact peak-track identity;
- support regained and downside absorption;
- a maximum 20-tradable-day holding period;
- two consecutive qualifying distribution days before the normal distribution exit;
- one-day soft-exit cancellation when structure is regained.

### Accumulation

`panel.py` computes the five causal setup-evidence components: turnover absorption, near-price chip growth, improving concentration, sticky structural peak evidence, and downside absorption. The score is their sum divided by five. The lifecycle starts from `NEUTRAL` or `BROKEN` only when the setup threshold is met. It freezes an immutable lineage root at that decision. Accumulation expires after three times the configured accumulation window in tradable-index terms.

The panel values are not all embedded in the chip shard, but they are exact deterministic projections from governed inputs. Their absence from a prebuilt decision ledger is therefore not data loss.

### Breakout

The breakout gate is `breakout_excess_atr >= 0.25`. At the breakout decision the machine freezes the exact support, ATR, volume, turnover, prior average cost, prior p50 cost, and breakout index. Later retest decisions use this frozen memory, not a rolling replacement.

The frozen values currently live in transient `LifecycleMemory`. They are exactly recoverable by replaying the lifecycle from the beginning of its governed observation sequence. A ledger should persist them so later audits do not need to inspect machine memory.

### Retest

Production has no separate approximate retest flag. After the minimum wait and before expiry, `_retest_qualified` evaluates all of the following against frozen breakout state and the immutable root:

- exact peak-track identity;
- exact root-retention availability;
- retest depth;
- volume contraction;
- turnover contraction;
- cost migration using both average and p50 costs;
- support regained;
- downside absorption;
- root-retention lower bound;
- model-disagreement bound;
- market regime;
- sector regime.

Every operand is either persisted or deterministically derived. A later ledger can therefore reproduce both successful and rejected evaluations. The audited five-symbol interval had no actionable retest evaluations, so this audit does not fabricate per-row rejection reasons that were never materialized. The positive and negative retest paths are instead covered by the focused regression evidence in Section 10.

## 5. Immutable V3 root-anchor semantics

`freeze_lifecycle_anchor` binds the lifecycle root to symbol, anchor date, sorted source snapshots, strategy version, current V3 peak-track ID, band, reference mass/cost, and peak count. The resulting root is self-referential through `root_anchor_id` and does not move when the working structural base changes.

Corporate-action rebasing adjusts the working comparison coordinates and frozen price/cost quantities. It does not replace or rewrite the lineage root. `exact_anchor_retention` accepts only exact root/date/symbol continuity and obtains bounds from the exact persisted-lineage resolver. Missing, ambiguous, or mismatched lineage fails closed; band overlap is not accepted as a substitute.

The validated V3 root-isolation regression demonstrates lifecycle root A remaining frozen while the rolling structural base becomes B. The focused audit regressions repeated that contract, including checkpoint and corporate-action paths.

## 6. Entry qualification and execution

`create_signal` hashes symbol, decision time, strategy version, parameter ID, and sorted snapshot IDs. It serializes the immutable root, working anchor, exact retention bounds, qualification context, and parameter identity.

Qualification, authorization, and execution scope must remain separate in the ledger:

1. **Qualified signal:** the lifecycle/retest contract passed.
2. **Formal authorization:** `order_authorized` is true only when `hard_valid`, complete edge-card evidence, and READY status are present.
3. **Research event-study request:** exact replay uses `RESEARCH_EVENT_STUDY`, which permits a qualified, hard-valid research signal even when formal calibration leaves it `BLOCKED_UNCALIBRATED`.

The exact entry resolver enforces:

- no same-bar or same-day fill;
- next legal market sessions only;
- at most three entry wait days;
- strictly ordered, unique five-minute windows;
- snapshot and hard-validity checks;
- trading-status, suspension, rule, corporate-action, OHLC, and limit-state checks;
- no buy through an up-limit lock;
- VWAP fill with configured slippage and impact;
- board-lot quantity and fee rules.

`EntryExecution.attempts` is currently transient and the standard exact-replay signal record persists only the aggregate status/fill and rejection reasons. Exact individual attempts are nevertheless reconstructible from registered five-minute windows. The future ledger should retain each attempt explicitly.

## 7. Exit lifecycle and execution

The open-position lifecycle evaluates only after a real future entry fill. Pending entry is not treated as an open position, and the machine cannot emit a pre-fill exit. The authoritative orchestration is `exact_replay.py`; the standalone signal-event stream is not a substitute for actual fill-state orchestration.

The open lifecycle preserves pending exit intent and handles:

- invalid/action-blocked observations;
- suspension without advancing tradable-day counters;
- exact root retention;
- structure break;
- protective stop against frozen support;
- maximum holding period;
- two-day distribution confirmation;
- one-day soft-exit cancellation when regained.

Exit execution also enforces T+1. Unlike entry, a risk-reducing sell does not expire after three days: missing windows, suspension, or a down-limit lock leave the exit pending, exposed, and accumulating tail loss until a legal fill. Entry-only up-limit/action blocks are not incorrectly reused for an exit.

The complete attempt sequence is reconstructible from the ordered registered execution windows. The future ledger should persist every pending attempt, gate result, exposure day, tail-loss increment, and final fill.

## 8. Minimum authoritative replay envelope

The post-hoc classification is valid only while all of the following remain immutable and addressable:

1. V3 root manifest, symbol manifests, feature parts, compact operator-lineage parts, checkpoints, journals, and their hashes.
2. Per-symbol input manifests, including the manifests currently referenced from the activated build workspace under `.v12_rolling_structural_base_v3_5symbol_20260827.building/input-manifests/`.
3. Registered raw daily, minute, corporate-action, identity, float, trading-status, limit-rule, and market-calendar inputs.
4. Registered five-minute execution windows and their snapshots.
5. Market and sector regime inputs used by the causal panel.
6. Strategy parameter manifest and exact parameter ID.
7. Strategy/chip code revision, semantic versions, schema versions, and configuration digests.
8. Exact company-action coordinate and lineage contracts.

The governed stage `COMPLETE.json` digest (`66c0b2940068864233a6a5ffadc19e20de7757da18dfff5539aefcec048e293b`) matches the referenced input manifests. Those input manifests are part of the replay contract and must not be discarded as disposable build residue.

The preferred ledger path reads the immutable V3 feature and compact operator-lineage artifacts, constructs the causal panel, and replays lifecycle/execution state without modifying chip data. The checkpoint/journal format also carries exact cell/lot state, float/latent supply, seller continuation, temporal-tracker continuation, dependency references, and exact state/model digests. Its reader validates replayed model digests rather than normalizing discrepancies. A real raw-input `ReplayBackend` is still required before checkpoint/journal-only lineage replay is production-ready.

If a future storage policy removes the compact operator lineage and relies only on checkpoint/journal plus raw inputs, bounded transition replay may be computationally necessary to answer lineage queries. That would be ledger computation, not a chip-shard rebuild: it must not regenerate, overwrite, or refingerprint the 500-symbol V3 chip dataset.

## 9. Five-symbol deterministic proof

The audit freshly replayed the governed 2018–2020 inputs for only the five approved symbols, projected the 2020 V3 feature rows, constructed a transient causal strategy panel, and replayed both the lifecycle and exact execution paths twice. No production artifact was written.

Fresh V3 feature output was Arrow-table exact to persisted output for every symbol:

| Symbol | Rows | Persisted vs fresh exact | Strategy-eligible rows | Maximum consecutive eligible history |
|---|---:|---:|---:|---:|
| `000001.SZ` | 243 | YES | 76 | 14 |
| `002260.SZ` | 243 | YES | 0 | 0 |
| `002706.SZ` | 243 | YES | 81 | 16 |
| `300604.SZ` | 243 | YES | 78 | 10 |
| `600519.SH` | 243 | YES | 36 | 12 |
| **Total** | **1,215** | **YES** | **271** | — |

No symbol reached the required 60-day actionable setup history in the audited 2020 interval. The accepted parameter therefore produced no setup lifecycle, breakout, qualified retest, entry intent, fill, open exposure, exit intent, or exit. These are authoritative zeros, not missing observations:

| Symbol | Setups | Breakouts | Qualified retests/signals | Research entry intents | Entry fills | Exit intents | Exit fills | Repeat exact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `000001.SZ` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| `002260.SZ` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| `002706.SZ` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| `300604.SZ` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | YES |
| `600519.SH` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | YES |

Invalid/peak-state changes still produced 36, 1, 26, 57, and 13 machine state-transition events respectively. Lifecycle replay was byte-for-byte repeatable between two fresh sessions, and exact-execution replay was exactly repeatable for all five symbols.

For the bounded proof only, the adapter converted the V3 feature timestamp from aware UTC to the older panel schema's local-naive representation and supplied `NULL` for the optional `chip_profile`, matching production `stream_panel` behavior. It also normalized absent positive-only observation values on rows first asserted to be non-actionable: 893 `structure_support` values and 1,010 each of prior average-cost and p50-cost values. No actionable row was altered. This is the adapter gap identified in Section 1 and must become an explicit fail-closed materializer contract rather than an audit-only normalization.

## 10. Focused verification

Twenty directly relevant regressions passed (`20 passed in 0.35s`). They cover:

- causal setup → breakout → retest;
- frozen-ATR retest depth and cost migration;
- fail-closed behavior for a different peak track;
- disagreement, market, and sector gates;
- two-day distribution confirmation;
- protective stop and frozen-support semantics;
- corporate-action rebasing;
- same-day prohibition and T+1 entry;
- up-limit delay and three-day entry failure;
- down-limit exit delay, pending exposure, and tail loss;
- delayed entry with no pre-fill exit;
- exact-replay lower-limit handling;
- immutable root A while rolling base becomes B;
- checkpoint/corporate-action exactness.

The five-symbol production interval contains no positive lifecycle, so the focused regressions are necessary evidence for positive and rejected paths. They do not replace the five-symbol exact artifact proof.

## 11. Minimal ledger design

The minimal production design is an append-only sibling artifact with two linked tables.

### Decision table — one row per `(symbol, decision_at, parameter_id)`

Persist:

- provenance: V3 root-manifest SHA, symbol-manifest SHA, source snapshot IDs, input-manifest SHA, code revision, semantic/schema versions, strategy version, parameter ID;
- PIT contract: `decision_at`, every `available_at`, calendar/tradable index, company-action coordinate/version, hard/research validity and exact rejection reason;
- V3 observation: tracked peak/episode/band/mass/prominence/flags/state and exact lineage status;
- lifecycle state before and after, lifecycle/root/working-anchor IDs, state-transition reason;
- every setup component, raw operand, score, and gate result;
- breakout excess and all frozen breakout fields;
- whether a production retest evaluation occurred, every raw retest ratio/value, every gate result, and aggregate qualification;
- exact root-retention lower/upper bounds, model values, resolver mode, and failure reason;
- signal ID, qualification, formal authorization status, edge-card/calibration reference, and execution scope;
- open-position lifecycle values, distribution-day counter, soft-cancellation state, protective-stop operands, holding days, exit reason, and pending exit ID.

### Execution-attempt table — one row per ordered entry or exit attempt

Persist:

- signal/position/exit-intent foreign keys;
- side, attempt ordinal, session date, window timestamp and snapshot ID;
- trade status, rule, action, limit, OHLC/VWAP, hard-validity, and exact gate outcome;
- requested and filled quantity, fill price, slippage, impact, fee, and cash effect;
- entry terminal failure or exit pending status;
- open exposure and tail-loss change for pending exits.

Both tables need their own schema version, deterministic sort/partition contract, content hashes, and root manifest. Their manifest should reference the V3 root hash; the V3 root manifest should not reference the ledger.

## 12. Rebuild and sequencing decision

The 500-symbol V3 temporal rebuild is safe to authorize independently of ledger implementation because no required ledger field was irrecoverably lost and no field needs to be inserted into the chip shard. The build must retain the complete replay envelope in Section 8.

Recommended sequence:

1. Freeze and retain all V3 root/symbol/input manifests, operator lineage, checkpoints/journals, registered inputs, calendars, versions, and hashes during the 500-symbol build.
2. Design the sibling decision and execution-attempt schemas against the pinned V3 root hash.
3. Fix the non-actionable observation adapter contract and implement/verify a real checkpoint replay backend only if checkpoint/journal resolution is selected.
4. Materialize the ledger post hoc from the immutable V3 dataset; prove repeatability, row counts, gate accounting, PIT semantics, T+1 semantics, and exact lineage failure behavior.
5. Only after that ledger proof, authorize the full strategy reverse study.

Rebuilding the 500 symbols now would not cause duplicate chip-shard work. Later ledger generation will necessarily perform strategy state replay and execution-window evaluation; that is the intended ledger computation, not a second V3 chip rebuild. No V3 chip shard should be regenerated solely because the ledger is added.

## 13. Hard gates

`EXACT_ACCUMULATION_REPLAYABLE: YES`

`EXACT_BREAKOUT_REPLAYABLE: YES`

`EXACT_RETEST_REPLAYABLE: YES`

`EXACT_ROOT_RETENTION_REPLAYABLE: YES`

`ENTRY_QUALIFICATION_REPLAYABLE: YES`

`ENTRY_EXECUTION_REPLAYABLE: YES`

`EXIT_LIFECYCLE_REPLAYABLE: YES`

`EXIT_EXECUTION_REPLAYABLE: YES`

`IMMUTABLE_ROOT_ANCHOR_REPLAY_VERIFIED: YES`

`LEDGER_CLASSIFICATION: POST_HOC_REPLAY_ARTIFACT`

`LEDGER_REQUIRES_CHIP_SHARD_SCHEMA_CHANGE: NO`

`LEDGER_REQUIRES_500_CHIP_REBUILD_IF_ADDED_LATER: NO`

`REBUILDING_500_NOW_WOULD_CAUSE_DUPLICATE_WORK: NO`

`SAFE_TO_DESIGN_LEDGER_IMPLEMENTATION: YES`

`SAFE_TO_REBUILD_500_TEMPORAL_DATA: YES`

`SAFE_TO_RUN_FULL_STRATEGY_REVERSE_STUDY: NO`
