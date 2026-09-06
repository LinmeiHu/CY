# V12 Lifecycle / Entry / Exit Ledger Implementation Report

## 1. Outcome

The lifecycle / entry / exit ledger is implemented as a deterministic post-hoc
replay artifact. It is a sibling of the governed V3 chip bundle and does not
modify, regenerate, reference from, or refingerprint any V3 chip shard.

The implementation reuses the scalar production `LifecycleMachine`,
`execute_entry`, and `execute_exit` engines. It does not define alternate
strategy economics, generic breakout/retest deltas, alternate fill timing, or
new strategy thresholds.

The governed five-symbol V3 bundle was replayed first. The resulting artifact
is:

- path: `/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_ledger_5symbol_20260828`
- V3 root-manifest SHA-256:
  `1ae9e08bd46bb13118e4cc6c59f27ccf0069527888d97f91bfd6887379c16f3b`
- parameter ID: `9baed76ec299161c`
- decision rows: `1,215`
- execution-attempt rows: `0` (the authoritative result for this interval)
- canonical ledger digest:
  `3a362eae3fca667b78713e2495563dc9a8b5aefc50cf8db2b39ac36dd5448b9b`
- fresh repeat equivalence: exact content equality, `YES`

No 500-symbol chip build, 500-symbol strategy replay, full-market run, or full
strategy reverse study was started.

## 2. Implementation

The new `src/cyq_game/strategy/lifecycle_ledger.py` provides:

1. `replay_lifecycle_entry_ledger` for one symbol and one parameter contract;
2. `merge_lifecycle_ledger_replays` for canonical symbol ordering;
3. `write_lifecycle_ledger_artifact` for immutable, idempotent artifact
   creation;
4. canonical decision and execution-attempt JSONL tables;
5. a canonical manifest containing table hashes, row counts, the overall
   digest, V3 root/symbol/input-manifest bindings, parameter identity, semantic
   identity, code commit, and exact code-file hashes.

The writer never overwrites an existing different artifact. Rewriting an
identical replay is verification-only and must match every byte. There is no
runtime creation timestamp in canonical content.

### Decision records

There is one row per `(symbol, decision_at, parameter_id)`. Each row includes:

- `decision_at`, `available_at`, and the PIT cutoff;
- V3 root, symbol-manifest, input-manifest, semantic, parameter, panel, and code
  provenance;
- lifecycle state before and after;
- deterministic decision-record, lifecycle/root, and signal IDs where the
  corresponding production concept exists;
- the immutable root anchor and the separately observed current rolling-base
  identity;
- setup score and the five production setup-evidence components;
- breakout excess plus frozen support, ATR, volume, turnover, and pre-breakout
  average-cost/p50 anchors;
- exact retest depth, cost migration, volume ratio, turnover ratio, root
  retention interval/model values, support recovery, downside absorption,
  seller-model disagreement, market, and sector gates when production evaluates
  a retest;
- open-position retention, structure, protective-stop, holding-period,
  distribution, and consecutive-confirmation gates;
- every evaluated gate, its value/operator/threshold, the first failed gate,
  and all failed gates;
- qualification, formal authorization, research entry intent, actual entry,
  exit intent/reason, actual exit, and lifecycle termination as separate facts.

Null is retained when a production quantity is unavailable or inapplicable. No
generic daily delta or synthetic retest detector is substituted.

### Execution-attempt records

Each ordered attempt records:

- signal/lifecycle/intent bindings and immutable root;
- decision time, decision-time `available_at`, attempt time, trade date, window
  index, and execution snapshot;
- side, aggregate execution status, legal-fill status, ordered reason codes,
  first/all failed execution gates;
- window presence, hard validity, trade status, market-rule status,
  corporate-action status, up/down limits, OHLC, volume, amount, and VWAP;
- exact configured next-window, maximum entry-wait, board-lot, fee, slippage,
  impact, and same-day prohibition contracts;
- actual fill time, price, quantity, notional, commission, and cash effect only
  on the legal fill attempt.

Entry and exit records therefore preserve the existing schedule:

`decision after close -> later market date -> first legal ordered five-minute window`

Entry still expires after three market dates. Exit remains pending through
suspension, missing windows, and lower-limit locks until a legal risk-reducing
sell exists. Same-day entry and exit fills remain forbidden.

## 3. Minimal readiness-gap fix

The audit's panel-adapter gap was confirmed and fixed narrowly.
`structure_support`, `prior_average_cost`, and `prior_cost_p50` are now nullable
inside `LifecycleObservation` only so a structurally non-actionable row can
reach the production machine's existing fail-closed/no-setup path without
invented zero or positive prices.

An actual breakout still requires all three authoritative positive operands.
Both scalar and vector research paths raise if an actionable breakout lacks
one. This changes no valid-row decision, threshold, lifecycle transition, or
strategy economics.

The checkpoint/journal `ReplayBackend` gap was not expanded in this task. The
ledger accepts the existing exact lineage resolver contract. No
checkpoint/journal-only fallback or silent lineage substitution was added.

## 4. Governed five-symbol proof

The causal panel was reconstructed transiently from registered daily inputs and
the governed V3 feature rows. The V3 aware timestamp was projected to the
existing panel's local-naive timestamp contract, optional missing panel columns
remained null, and the audited non-actionable operands remained null. No chip
shard or panel artifact was rewritten.

The replay reproduced the audit counts:

| Symbol | Decision rows | Hard-valid, tradable rows | Setup/root/breakout/retest/signal/entry/exit |
|---|---:|---:|---:|
| `000001.SZ` | 243 | 76 | 0 |
| `002260.SZ` | 243 | 0 | 0 |
| `002706.SZ` | 243 | 81 | 0 |
| `300604.SZ` | 243 | 78 | 0 |
| `600519.SH` | 243 | 36 | 0 |
| **Total** | **1,215** | **271** | **0** |

There were 133 lifecycle state changes, matching the audit's per-symbol total.
All 1,215 rows were correctly classified as having no actionable setup under
the accepted 60-day history and `1.00` setup contract. Consequently there are
no manufactured breakout, retest, qualification, execution, or exit rows.

Two fresh in-memory replays were exactly equal. Rewriting the same target was
also accepted only after every canonical file matched.

## 5. Focused validation

The new focused suite has seven tests and covers:

- PIT/`available_at` rejection;
- accepted parameter-ID binding;
- exact setup score and component evidence;
- exact frozen breakout support/ATR/volume/turnover/pre-cost fields;
- exact retest depth, cost migration, volume ratio, turnover ratio, root
  retention bounds, and seller-model disagreement rejection;
- qualification versus formal authorization versus research entry intent
  versus actual legal entry;
- qualified-but-three-day-unfilled entry failure;
- same-day prohibition, suspension, upper-limit entry delay, lower-limit exit
  delay, actual entry, protective-stop exit intent, and actual exit;
- immutable root A while the current V3 rolling base becomes B;
- byte-identical artifact replay and idempotent identical write;
- direct equality of signal ID, entry time, exit reason, and exit time against
  `evaluate_exact_parameter_lattice_symbol`.

Validation results:

- new ledger tests: `7 passed`;
- directly related existing lifecycle, execution, exact replay, signals, and
  research tests: `95 passed`;
- targeted Ruff: passed;
- targeted strict mypy for the new materializer: passed;
- full-repository validation: not run, per task scope.

## 6. Schema and semantic isolation

No file under the V3 chip bundle was changed. No chip schema, checkpoint,
journal, feature schema, root manifest, rolling structural base, root-anchor
rule, strategy parameter, lifecycle threshold, or execution rule was modified.

The only changed production files outside the new ledger module are the three
small adapter fail-closed changes in:

- `src/cyq_game/strategy/markup_retest.py`;
- `src/cyq_game/strategy/signals.py`;
- `src/cyq_game/strategy/research.py`.

The ledger is safe to bind to a frozen 500-symbol V3 bundle only when the full
authoritative replay envelope from the readiness audit is retained and its
hashes match. Unknown or mismatched lineage still fails closed.

The ledger proof clears the implementation prerequisite for a full strategy
reverse study. It does not authorize altering strategy economics, and it does
not mean the full 500 replay was performed in this task.

LEDGER_IMPLEMENTED_AS_POST_HOC_ARTIFACT: YES
CHIP_SHARD_SCHEMA_CHANGED: NO
ROLLING_BASE_V3_SEMANTICS_CHANGED: NO
PRODUCTION_STRATEGY_SEMANTICS_CHANGED: NO
EXACT_ACCUMULATION_REPLAY_VERIFIED: YES
EXACT_BREAKOUT_REPLAY_VERIFIED: YES
EXACT_RETEST_REPLAY_VERIFIED: YES
EXACT_ROOT_RETENTION_REPLAY_VERIFIED: YES
ENTRY_QUALIFICATION_REPLAY_VERIFIED: YES
ENTRY_EXECUTION_REPLAY_VERIFIED: YES
EXIT_LIFECYCLE_REPLAY_VERIFIED: YES
EXIT_EXECUTION_REPLAY_VERIFIED: YES
IMMUTABLE_ROOT_ANCHOR_VERIFIED: YES
DETERMINISTIC_LEDGER_REPLAY_VERIFIED: YES
FIVE_SYMBOL_LEDGER_VALID: YES
SAFE_TO_BIND_LEDGER_TO_FROZEN_500: YES
SAFE_TO_RUN_FULL_STRATEGY_REVERSE_STUDY: YES
