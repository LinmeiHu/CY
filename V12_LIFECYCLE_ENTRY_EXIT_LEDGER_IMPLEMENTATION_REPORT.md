# V12 Lifecycle / Entry / Exit Ledger Implementation Report

## 1. Result

The lifecycle, decision-gate, and execution ledger is implemented as a deterministic,
append-only `POST_HOC_REPLAY_ARTIFACT`. It observes the existing scalar production
replay and does not replace or modify strategy transitions, thresholds, fills, exit
rules, chip state, or frozen V3 shards.

The implementation commit bound into both final manifests is:

`3488a95dfb17815e7ea23f065c702106dcd10437`

The accepted parameter ID remains:

`9baed76ec299161c`

The authoritative 500-symbol output is:

`/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_exit_ledger_500_20260828`

The governed five-symbol validation output is:

`/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_exit_ledger_5symbol_20260828`

No downstream study and no 3,941-symbol build was started.

## 2. Authoritative implementation map

| Decision or state | Authoritative production source | Ledger treatment |
|---|---|---|
| Accumulation components and score | `panel._create_panel_table` | Records the five component predicates, exact `setup_score`, and `setup_score_min` |
| Rolling structural-base observation | `signals.observation_from_record` and `LifecycleObservation.peak_identity_valid` | Records observed `peak_track_id`, V3 peak versions, availability, and snapshot IDs |
| Setup creation and immutable root binding | `LifecycleMachine.advance` and `freeze_lifecycle_anchor` | Observes the canonical transition; emits `SETUP_OBSERVED` and `ROOT_ANCHOR_BOUND` |
| Breakout qualification and frozen state | `LifecycleMachine.advance` | Records exact breakout excess/threshold and the resulting frozen support, ATR, volume, turnover, and pre-breakout costs |
| Retest qualification | `LifecycleMachine._retest_qualified` | Records exact frozen-ATR depth, cost migration, volume/turnover ratios, support, absorption, market, and sector operands |
| Exact root retention | `exact_anchor_retention` via `StreamingLineageSession` over registered CY-018 operators | Records the exact lower-bound operand and configured 70% threshold; unknown lineage fails closed |
| Root destruction | `chip_structure_broken` | Records the canonical root-structure result without substituting band occupancy or daily deltas |
| Seller-model disagreement | `LifecycleMachine._retest_qualified` | Records the exact disagreement-in-ATR operand and fixed production threshold |
| Signal qualification | `LifecycleMachine.create_signal` | Observes the production signal and preserves its production signal ID |
| Entry scheduling and fill | `execute_entry`, `resolve_next_legal_fill`, and `_window_rejection_reasons` | Separates qualification, intent, rejected attempts, defer/failure, and fill |
| Holding/exit decision | `LifecycleMachine._advance_open`, `distribution_score_with_anchor`, and `chip_structure_broken` | Records protective stop, exact distribution state, confirmation count, root failure, and max holding in production order |
| Exit intent | `exact_replay._exit_intent` | Preserves canonical reason, timestamp, signal, quantity, availability, and snapshots |
| Exit scheduling and fill | `execute_exit` and `_exit_window_rejection_reasons` | Separates condition, intent, attempts, blocked exposure, and actual fill |
| Corporate-action coordinate | `rebase_lifecycle_memory` and exact replay position-action handling | Keeps root lineage identity immutable while rebasing comparison/support/ATR/cost/position coordinates once |
| Lifecycle termination | Canonical filled-exit handling in exact replay | Emits termination only after an actual exit fill |

`exact_replay.ExactReplayAuditSink` is a read-only observer protocol. The scalar replay
still calls `LifecycleMachine.advance`, `execute_entry`, `_exit_intent`, and
`execute_exit`; the sink receives their completed canonical values. The observer never
returns a decision or mutates replay state.

## 3. Frozen V3 adapter

The frozen V3 candidate files are narrower than the legacy feature schema consumed by
the production causal panel. `build_frozen_v3_panel` performs a read-only projection of
the frozen V3 fields, joins registered CY-008 minute summaries where present, and then
calls the existing `_create_panel_table` implementation. It does not modify or rewrite
the frozen candidates.

Invalid positive-only observations and invalid/non-positive quantile profiles are kept
representable only with a constructor-safe sentinel and are simultaneously forced to
`hard_valid=False`. The sentinel cannot authorize a setup or signal. No invalid value is
normalized, clipped, or treated as research-valid.

The adapter reproduced the readiness-audit five-symbol facts exactly: 1,215 panel rows,
five symbols, 271 research-valid rows, zero strict rows, and zero signals.

## 4. Ledger schema

Four deterministic Parquet tables are produced:

| Artifact | Purpose |
|---|---|
| `lifecycle_events.parquet` | State/event sequence, before/after state, root/base/signal identities, PIT timestamps, reason, terminal flag, failed-gate attribution, snapshots, and frozen memory details |
| `decision_gates.parquet` | One normalized row per exact gate operand, including phase, production order, typed observed value, operator, threshold, pass/fail, blocking status, first-failed flag, reason code, and source function |
| `execution_events.parquet` | Entry/exit intent, every rejected attempt, deferred/failed/blocked terminal event, or fill with exact window, limits, status, VWAP/OHLC, price, quantity, cash, and blocked tail loss |
| `lifecycle_summary.parquet` | Compact per-root lifecycle summary requested for later research |

Large chip distributions are not duplicated. Rows reference immutable snapshot IDs and
root/base identities.

Every table row repeats the governed root SHA, freeze-lock SHA, V3 build commit, ledger
implementation commit, parameter ID, strategy version, semantic fingerprint, artifact
contract fingerprint, execution/config fingerprint, and ledger schema version.

## 5. Stable lifecycle identity and V3 root isolation

The lifecycle ID is SHA-256 over:

`ledger schema | LIFECYCLE | symbol | parameter ID | immutable root anchor ID | root creation date`

The current rolling structural base is recorded separately as
`rolling_structural_base_id`. It is never an input to lifecycle identity. Corporate
actions may rebase the comparison anchor and frozen price references, but do not mutate
the immutable accumulation/root anchor identity.

The regression suite verifies that a lifecycle rooted at A remains rooted at A when the
observed rolling base becomes B. In the frozen 500 replay, the sole lifecycle retained
one root ID and one rolling-base identity over all its observed dates.

## 6. Gate representation and attribution

Gate rows contain both JSON-preserving values and typed numeric/boolean/text columns.
`blocking` distinguishes production decision gates from explanatory component evidence.
`first_failed` is derived deterministically from canonical production order. All failed
blocking gates remain queryable, including failures occurring with an earlier primary
failure.

The accepted exact operands remain unchanged, including setup score 1.00, breakout
excess 0.25 ATR, retest depth 0.50 ATR, cost migration 0.50 ATR, retest volume ratio
0.80, retest turnover ratio 0.80, and root retention 70%.

## 7. Entry and execution replay

The representation keeps these events distinct:

`SETUP -> QUALIFIED -> ENTRY_INTENT -> ENTRY_EXECUTION_ATTEMPT -> ENTRY_FILLED`

The production signal is formed at 15:30+08:00 and cannot fill on that trading date.
The execution layer uses the next legal registered 5-minute window, including suspension,
market-rule, limit, corporate-action, OHLC/unit, duplicate/missing-window, and VWAP gates.
Three-day entry failure and insufficient-calendar pending status remain explicit.

No frozen five- or 500-symbol lifecycle qualified under the accepted parameter during
this 2020 replay, so both final execution tables are valid typed zero-row Parquet
artifacts. Positive qualification, intent, T+1 fill, failure, and collector separation
are covered by the focused regression suite and the unchanged production replay tests.

## 8. Exit decision and execution replay

The representation keeps these events distinct:

`EXIT_CONDITION -> EXIT_INTENT -> EXIT_EXECUTION_ATTEMPT -> EXIT_FILLED`

The observer records the production order: corporate-action/data/peak validity,
tradability, exact lineage availability, root destruction, protective stop, max holding,
distribution score, and consecutive confirmation. Exit execution remains pending through
suspension or a pinned lower limit and records blocked tail loss when production computes
it.

No actual entry filled in either frozen validation replay, so no real-data exit condition
or exit fill exists in these artifacts. Protective-stop, distribution-confirmation,
max-holding, blocked exit, T+1 exit fill, and collector termination paths are covered by
the focused regression suite and existing production execution tests.

## 9. PIT and corporate-action guarantees

The observation constructor enforces `available_at <= decision_at`. The collector checks
the same invariant before appending lifecycle, gate, and execution rows. Execution rows
use the attempt/fill timestamp as their decision timestamp and preserve the earlier
intent timestamp separately, so a future legal window is never represented as available
to the original signal decision.

DuckDB audits over both final artifact sets found zero rows with
`available_at > decision_at` in all three normalized ledgers.

The causal panel continues to resolve QD-010 through the registered immutable inventory.
No alternate research coordinate was introduced.

## 10. Five-symbol validation

Symbols: `000001.SZ`, `002260.SZ`, `002706.SZ`, `300604.SZ`, `600519.SH`.

Fresh scalar production replay and observed ledger replay were exactly equal. Replays A
and B were exactly equal, including semantic rows and final Parquet hashes.

| Measure | Count |
|---|---:|
| Input/evaluation rows | 1,215 |
| Setups | 0 |
| Root bindings | 0 |
| Breakouts | 0 |
| Retests | 0 |
| Qualifications | 0 |
| Rejection events | 1,110 |
| Entry intents / fills | 0 / 0 |
| Open holdings | 0 |
| Exit intents / fills | 0 / 0 |
| Lifecycle terminations | 0 |

All-failed gate distribution: `hard_valid=1,010`, `peak_identity_valid=893`,
`setup_score=205`. Deterministic first-failed distribution:
`hard_valid=1,010`, `setup_score=205`.

The five-symbol lifecycle table also contains 105 validity-driven state transitions;
these are not fabricated setups or rejection events.

## 11. Frozen 500-symbol replay

| Measure | Count |
|---|---:|
| Symbols | 500 |
| Input/evaluation rows | 121,251 |
| Lifecycle-event rows | 121,252 |
| Decision-gate rows | 555,418 |
| Execution-event rows | 0 |
| Lifecycle summaries | 1 |
| Setups / root bindings | 1 / 1 |
| Breakout observations / rejections | 0 / 9 |
| Retests / qualifications | 0 / 0 |
| Entry intents / fills / open holdings | 0 / 0 / 0 |
| Exit intents / fills / terminations | 0 / 0 / 0 |
| Rejection events | 110,010 |

The sole setup was `000709.SZ` on 2020-12-18, with lifecycle ID
`b3267301729d1997a75a8a5d518bbf720af2c8571478f2235fc35033d360c975`
and immutable root ID
`d0569e263287021f871104122a7dab4233f5b5063100314756f72906cd26d51c`.
It remained `ACCUMULATING` through year end and had no breakout qualification.

All-failed gate distribution:

| Gate | Count |
|---|---:|
| `hard_valid` | 93,515 |
| `peak_identity_valid` | 79,632 |
| `setup_score` | 27,316 |
| `tradable` | 410 |
| `corporate_action_clear` | 59 |
| `breakout_excess_atr` | 9 |

Deterministic first-failed distribution:
`hard_valid=93,456`, `setup_score=27,316`, `tradable=410`,
`corporate_action_clear=59`, `breakout_excess_atr=9`.

Counts are descriptive only. No threshold or strategy judgment was made.

## 12. Deterministic replay evidence

The five and 500 builds each ran replay A and replay B from the same immutable inputs.
Both compared exact replay results, normalized ledger table digests, and serialized
Parquet SHA-256 values. Every comparison passed.

The 500 normalized table digest was:

`7f5a0b5a80443a35079b37a8171bd6a03cbca807e92cf3a9256b340502426803`

The five-symbol normalized table digest was:

`72df3a34c3d04f70f47987093e889c439f364226d70cc456e483969fe22db871`

## 13. Frozen chip immutability evidence

Before and after the full replay, the builder verified every manifest-bound file by size
and SHA-256:

| Check | Before | After |
|---|---|---|
| Files | 13,479 | 13,479 |
| Bytes | 4,287,243,945 | 4,287,243,945 |
| Deterministic tree SHA-256 | `e33fb84ecabfd33f8bb357569a1d57086ac2acf4d201c00e4e2b5d61aa085d91` | `e33fb84ecabfd33f8bb357569a1d57086ac2acf4d201c00e4e2b5d61aa085d91` |

Final direct hashes remain:

* root manifest: `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a`
* freeze lock: `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9`

The ledger output is outside the frozen root. No frozen chip file was opened for write.

## 14. Artifact hashes

### 500-symbol artifacts

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `lifecycle_events.parquet` | 121,252 | `66a120d028a268696df8a5b85702a4ca0d7db95da8639134de8310da35ac65e7` |
| `decision_gates.parquet` | 555,418 | `35817766cf05f6b7a5e77078735f6226698fd51955204926ae852f6a1f111381` |
| `execution_events.parquet` | 0 | `7cb6111adb970b9b4cff51f511e0fadc46ca4698ef996f6068dea1b4d99f432b` |
| `lifecycle_summary.parquet` | 1 | `7d1d9876a0cc98140380f9fc497449bea27a792a428be1f240a5ed29bdce6b3e` |
| `manifest.json` | — | `4b4ba0325f41dfcda5f9a7e8e3f259907dbf596f5b2863f622bf2503c7e30254` |

### Five-symbol artifacts

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `lifecycle_events.parquet` | 1,215 | `d8e9b2f819b2febaefc3c50d153cc104b0a71fea491c67e1f031951778a33cc0` |
| `decision_gates.parquet` | 5,080 | `51aa240d5f8c8dccedc01e691f0eb2d243981a0bd97345ba81e74ff4cf256d48` |
| `execution_events.parquet` | 0 | `7cb6111adb970b9b4cff51f511e0fadc46ca4698ef996f6068dea1b4d99f432b` |
| `lifecycle_summary.parquet` | 0 | `c6d7cad46043279aaf4e8e50551d58d2b77be85f1df18f146820e66f2fb1be67` |
| `manifest.json` | — | `39a8f021e897aab3a6cf18663bee21a830127b0f9b1aaee799475745d4b62afb` |

## 15. Tests

Focused ledger suite: 27 passed. It covers all requested identity, root isolation,
accumulation, breakout, retest, retention, gate attribution, entry/exit distinction,
next-window execution, blocked/deferred execution, exit rules, corporate actions, PIT,
repeat replay, provenance rejection, frozen-file immutability, invalid-quantile fail-closed
handling, and a positive collector path through qualification, entry fill, exit intent,
exit fill, and termination.

Directly related unchanged production suites: 83 passed across lifecycle, execution,
exact replay, and signal generation. After the invalid-quantile regression, the directly
affected signal/exact replay subset also passed 19/19.

Full repository validation was not run, consistent with the repository workflow rule.

## 16. Limitations and Reverse Study V2 readiness

This artifact covers the governed 2020 frozen universe and the accepted parameter only.
It is not a portfolio ledger, calibration artifact, performance study, or strategy
optimization. Execution tables are empty because no frozen lifecycle qualified; their
schema and positive/blocked behavior are verified by regression rather than fabricated
real-data events. The five-symbol source has sparse valid histories, so its zero setups
are expected and faithfully retained.

The ledger is exact and provenance-bound for later Reverse Study V2 attribution. Reverse
Wave V2, continuation, and reverse-exit studies are safe to start as separate explicit
tasks. No such study was started here. The 3,941-symbol build remains explicitly out of
scope and not authorized by this report.

## 17. Final hard gates

`LEDGER_IMPLEMENTED_AS_POST_HOC_ARTIFACT: YES`

`FROZEN_500_CHIP_DATA_MUTATED: NO`

`FIVE_SYMBOL_LIFECYCLE_REPLAY_EXACT: YES`

`ACCUMULATION_VALUE_EXACT: YES`

`BREAKOUT_VALUES_EXACT: YES`

`RETEST_VALUES_EXACT: YES`

`ROOT_RETENTION_EXACT: YES`

`ROOT_ANCHOR_ISOLATION_VERIFIED: YES`

`ENTRY_QUALIFICATION_EXACT: YES`

`ENTRY_EXECUTION_EXACT: YES`

`EXIT_DECISIONS_EXACT: YES`

`EXIT_EXECUTION_EXACT: YES`

`PIT_AUDIT_PASS: YES`

`REPLAY_REPEAT_DETERMINISTIC: YES`

`FROZEN_ROOT_MANIFEST_SHA_UNCHANGED: YES`

`FROZEN_LOCK_SHA_UNCHANGED: YES`

`500_LEDGER_BUILD_COMPLETE: YES`

`SAFE_TO_RUN_REVERSE_WAVE_V2: YES`

`SAFE_TO_RUN_CONTINUATION_STUDY: YES`

`SAFE_TO_RUN_REVERSE_EXIT_STUDY: YES`

`SAFE_TO_START_FULL_MARKET_3941_BUILD: NO`
