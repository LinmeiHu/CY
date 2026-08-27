# V12 Temporal Peak Lifecycle Audit

Date: 2026-08-27

Validated baseline: `9667568eae403aaf044888871f720c4c3a50e53b`

Audit branch: `audit/v12-temporal-peak-lifecycle`

Production tracker version: `temporal-chip-peak-v2`

## Outcome

The unchanged continuous 2018--2020 tracker produces zero valid 2020 bases
because `TemporalPeakTracker._base_track_id` is assigned once and never cleared
or replaced. A lost identity is correctly removed from future matching, and
later peaks are correctly born with new identities, but the retained base ID
becomes an orphaned tombstone. No later identity can become
`tracked_base_peak`, regardless of its age or persistence.

This is not a peak-matching or lost-identity-reattachment defect. It is the
explicit current V2 behavior and is covered by the existing lost/reappearance
test plus the new lifecycle characterization. It is, however, a **DESIGN
LIMITATION** for research that requires a rolling current structural base. The
code has conflated a one-time symbol-history base binding with the rolling
daily structural role consumed by the panel. It has not conflated the Python
objects themselves: the strategy already has a separate immutable
`LifecycleAnchor`, exact root-lineage retention, and entry memory.

The year-local builder reset is independently a **BUILD CONTINUATION DEFECT**.
It caused the rejected `57 / 1,215` non-null and `46 / 1,215` strict-valid 2020
figures. Fixing only that defect would faithfully reproduce the currently
intended V2 one-shot semantic, but would still produce `0 / 1,215` 2020
coverage. It is therefore not safe to merge a continuation-only correction or
start a wider rebuild before a separately reviewed and versioned rolling-base
design exists.

The primary classification is a combination of:

- **B — builder state-continuation defect:** tracker state starts at the output
  boundary instead of the governed-history boundary;
- **C — intentional but unsuitable identity semantic:** identities die
  permanently, and the V2 base binding is one-shot;
- **D — rolling-base/root-like binding confusion:** the one-shot base pointer
  is used as a daily market-state feature even though a true immutable strategy
  root already exists separately.

No core tracker **DEFECT** against the currently encoded V2 semantics was
demonstrated. Changing post-loss base promotion is a **DESIGN CHANGE**, not a
bug fix that may be made in this audit.

## Evidence and audit boundary

The audit used only the five requested symbols and the governed staged inputs
at:

`/Users/linmei/Documents/CY/data/validation/v12_rc1_2020_stage`

The read-only diagnostic shared one unchanged
`EnsembleTemporalPeakTracker` across the 2018, 2019, and 2020 annual replay
calls. Chip state crossed years through the existing exact terminal snapshot
path. No production artifact was written; the detailed diagnostic JSON was
written under `/tmp`.

The replay covered 729 transition days per symbol, 3,645 total. Its 2020
result exactly reproduced the prior continuous diagnostic:

| 2020 effective state | Rows |
|---|---:|
| `ENSEMBLE_PEAK_AMBIGUOUS` | 884 |
| `TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS` | 331 |
| `TRACKED` | 0 |
| Total | 1,215 |

All `1,215` rows have no effective tracked base. Strict-valid coverage is also
zero. The event flags overlap those states: 66 split days, 94 merge days, and
138 lost-event days.

The synthetic audit suite contains eight passing tests for cases A--G in
`tests/test_temporal_peak_lifecycle_audit.py`. Existing corporate-action and
ensemble tests remain authoritative for those operations.

## Authoritative state machine

The table below describes executable rules, not implications inferred from
field names.

| Operation | Authority | Current rule | Invariant and identity scope |
|---|---|---|---|
| Candidate peak birth | `chip/peaks.py::detect_canonical_peaks` | Detect daily, price-ordered structural modes after fixed smoothing, mass, prominence, non-maximum-suppression, and valley rules. A `CanonicalPeak` has no temporal ID. | Daily observation only; no cross-day identity. |
| Local track creation | `TemporalPeakTracker.update`, `_new_track_id` | Every candidate not claimed by an old track gets a hash of version, symbol, model, date, and candidate buckets; age starts at 1. | New episode identity. It never reuses a lost ID. |
| Track matching | `TemporalPeakTracker.update`, `_match_score` | Build all old/new compatible pairs using band IoU and log-center distance. Non-overlap is allowed only within 1%. | Causal T-to-T+1 matching from active prior observations only. |
| Continuation | `TemporalPeakTracker.update` | Each old track chooses its highest-scoring candidate; the chosen observation retains the ID and increments age. | Identity persists only through an accepted daily match. |
| Split | `TemporalPeakTracker.update` | More than one compatible new candidate for an old track marks the chosen continuation `split=True, ambiguity=True`; unclaimed children are new identities and ambiguous when they had an old option. | The old ID may continue through one child. Split is an invalid event, not automatic death. If the chosen child stabilizes, the same base ID can recover. |
| Merge | `TemporalPeakTracker.update` | More than one old track compatible with one new candidate marks the claimant ambiguous/merge. Price-order iteration lets the first claimant continue; later claimants become lost merge events. | One old identity may continue; the others die. Merge is invalid on the event day and can recover only through the continuing identity. |
| Lost | `TemporalPeakTracker.update` | No compatible option, or an already-claimed new candidate, emits `lost=True, ambiguity=True`. Lost rows appear in that day's result but are excluded from tomorrow's `_previous`. | Permanent identity death. Episode-scoped ID; no resurrection. |
| Ambiguity | `TemporalPeakTracker.update` | Split, merge, score tie, duplicate claim, or a dominant mass margin below 0.02 marks ambiguity. | Fail closed for base use on the affected day. Ambiguity itself is not necessarily permanent. |
| Dominant peak | `TemporalPeakTracker.update` | Maximize rounded mass, then rounded prominence, then lower center price. Lost events are excluded. | Daily rank only. Dominance changes do not rewrite a live base identity. |
| Initial tracked base | `TemporalPeakTracker.update` | When `_base_track_id is None`, assign the first non-ambiguous dominant ID. | One-time tracker-instance binding. This is permanent in V2. |
| Tracked-base lookup | `TemporalPeakTracker.update` | Return the active observation with `_base_track_id` only when it is non-ambiguous. | Same-ID continuity; never substitutes today's dominant. |
| Base loss | `TemporalPeakTracker.update` | If the saved base ID is absent or ambiguous, return no base and `TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS`. Do not clear the saved ID. | The saved ID becomes an absorbing tombstone once permanently lost. |
| New track after base loss | `TemporalPeakTracker.update` | Unclaimed candidates continue to receive new IDs and can age normally. | Allowed; identity B is distinct from dead identity A. |
| Promotion after base loss | No transition exists | `_base_track_id` is non-null forever, so the initial-assignment condition can never run again. | Impossible in V2, even for a persistent, unambiguous B. |
| Look-alike reappearance | Lost comment in `TemporalPeakTracker.update`; existing `test_peak_merge_and_lost_reappearance_fail_closed` | A later candidate near A is evaluated only against currently active tracks. If unclaimed, it is born as B. | A remains dead. B may exist, but cannot become the V2 base. |
| Prohibited reattachment | Same authority | Lost events are never placed in `_previous`; no tombstone is offered to `_match_score`. | Permanent and intentional safety invariant. |
| Corporate-action rebase | `TemporalPeakTracker.apply_corporate_action`; `EnsembleTemporalPeakTracker.apply_corporate_action` | Rebase active bands and centers exactly once per action ID for all three local trackers and the ensemble tracker. IDs and ages do not change. | Same economic peak on the ex-date coordinate; action IDs are permanent scope state. |
| Seller-model-local tracking | `EnsembleTemporalPeakTracker.update` | Advance one independent `TemporalPeakTracker` per exact seller model. | IDs are model-local episodes. |
| Ensemble matching | `_ensemble_candidates` | Use `ACTIVE_STICKY` as lexical anchor; require a unique compatible candidate in `DISPOSITION` and `UNIFORM`; reject ties and many-to-one mappings; form median consensus candidates. The ensemble tracker then advances on those candidates. | Exact three-model, one-to-one, fail-closed same-day correspondence. Ensemble IDs are separate episodes, not concatenated local IDs. |
| Missing model | `EnsembleTemporalPeakTracker.update` | A missing, duplicate, or unknown seller identity cannot produce a valid ensemble base. | Exact seller-model coverage remains mandatory. |

### Identity invariant

If `track_A` is lost, must `track_A` remain dead permanently?

**YES.** It is removed from `_previous`, so it can never be a later matching
source. Corporate actions do not revive it. This remains an intentional safety
contract.

### New-base invariant

After A is permanently lost, may a genuinely new B be born?

**YES.** Cases C and D prove that B receives a different deterministic ID and
can continue with ages 1, 2, 3, and 4.

May B later become the current V2 `tracked_base_peak`?

**NO.** Case C proves that a distinct, unambiguous B remains dominant and ages
for four observations while every base result remains null. The five-symbol
replay is stronger: after the absorbing loss, each symbol creates 67--279 new
ensemble identities, and one `002260.SZ` post-loss identity persists to age
427, yet no new base ID is ever selected.

There is no stability threshold that B is waiting to satisfy. V2 has no
post-loss promotion transition at all.

## Synthetic cases A--G

| Case | Result under unchanged V2 |
|---|---|
| A — ordinary continuation | One ID, ages 1/2/3. |
| B — permanent loss | A emits one terminal lost event and never appears in later active peaks. |
| C — unrelated B | B is born, persists, and is dominant; B never becomes base. |
| D — look-alike | Near-price B gets a new ID; A is not reattached; B still cannot become base. |
| E — split then stabilization | Split day fails closed; the best-matching child retaining A can recover A on stabilization. |
| F — merge then stabilization | Merge day fails closed; the claiming continuation can recover only if it retained the base ID. |
| G — year boundary | Continued warmup/output calls equal one continuous tracker exactly. A fresh output-year tracker diverges in ID and age. |

Case G proves that a calendar-year boundary has no economic or tracker
semantic. The production divergence is therefore a builder defect.

## Rolling base versus immutable strategy root

The code has a separate immutable lifecycle representation already:

- `LifecycleAnchor` stores `anchor_id`, `root_anchor_id`, parent, role, creation
  date, frozen band, reference mass, and the peak ID observed at creation.
- `freeze_lifecycle_anchor` requires a currently valid tracked peak and creates
  an immutable `ROOT` identity from the symbol, causal date, snapshots, and
  strategy version.
- `LifecycleMemory` separately keeps the accumulation root, comparison anchor,
  working support anchor, anchor chain, breakout date/support/ATR/volume,
  pre-breakout costs, and active signal state.
- `exact_anchor_retention` resolves exact descendants against the frozen root
  ID, symbol, anchor date, and current decision date.
- `maybe_create_support_anchor` can advance a working support while preserving
  the immutable root.
- `_retest_qualified`, `chip_structure_broken`, and
  `distribution_score_with_anchor` require the current observed peak ID to
  remain the frozen lifecycle peak ID. Destruction of A correctly breaks that
  setup rather than rewriting its root to B.
- `StrategySignal` persists root, working, and chain identities for entry
  memory.

The lifecycle machine can reset a broken, inactive setup and form a later new
setup. That later setup should be able to freeze whatever daily structural
base is valid then. V2's orphaned symbol-history base pointer prevents the
daily feature from ever becoming valid again, so the lifecycle never gets the
opportunity.

Therefore `tracked_base_peak` is **not** the immutable strategy root anchor.
Nor does V2 implement it as a rolling structural base. It is a third,
one-time symbol-history binding whose terminal behavior makes it unsuitable
for the desired daily role. Defining a safe `A -> lost -> B` promotion policy
requires a separately versioned design. This audit does not invent that rule.

The checkpoint contract has a `reappear` bit, but runtime `TrackedPeak` has no
reappearance state and the daily feature writer never emits `REAPPEAR`.
Current safe behavior is represented by a lost A event followed by a new B
birth. Treating the dormant bit as permission to reattach would be incorrect.

## Five-symbol causal timelines

All dates are governed replay dates. “Absorbing loss” is the first date on
which the saved base ID is absent from active ensemble tracks and never returns.

| Symbol | First candidate / birth / valid base | First ambiguity / split / merge / lost | Absorbing base loss | New births in absorbing episode | Long-lived later evidence |
|---|---|---|---|---:|---|
| `000001.SZ` | 2018-01-03 / same / same | 2018-01-10 / 01-10 / 01-10 / 01-12 | 2018-01-12 | 102 | First post-loss births 2018-01-15; one later track reaches age 240. |
| `002260.SZ` | 2018-06-05 / same / same | 2018-06-15 / 2018-07-24 / 06-15 / 06-15 | 2018-07-04 | 85 | B is born on the absorbing date; one later track reaches age 427 on 2020-12-31. |
| `002706.SZ` | 2018-01-03 / same / same | 2018-01-18 / 01-18 / 01-18 / 01-19 | 2018-05-24 | 79 | First post-loss birth 2018-06-07; one later track reaches age 141. |
| `300604.SZ` | 2018-01-03 / same / same | 2018-01-04 / 2018-01-11 / 01-04 / 01-04 | 2018-01-04 | 279 | First post-loss births 2018-01-05; one later track reaches age 68. |
| `600519.SH` | 2018-01-03 / same / same | 2018-01-11 / 2018-01-17 / 01-17 / 01-11 | 2018-01-30 | 67 | First post-loss birth 2018-02-05; one later track reaches age 335. |

“First lost” can concern a non-base track and therefore precede the absorbing
base loss. Split/merge/lost event flags also concern every active ensemble
track, not only the base.

### State entering 2020

| Symbol | Saved base ID | Active peaks on 2019-12-31 | Ages | Effective state |
|---|---|---:|---|---|
| `000001.SZ` | `peak-3492b272cd374c2302e2` (absent) | 4 | 32, 78, 65, 51 | ensemble ambiguous |
| `002260.SZ` | `peak-2ea9262471d86769b34b` (absent) | 4 | 183, 184, 172, 172 | ensemble ambiguous |
| `002706.SZ` | `peak-280d83421d7f1e03477a` (absent) | 4 | 10, 91, 16, 77 | tracked base lost/ambiguous |
| `300604.SZ` | `peak-69244d42df494a3a307b` (absent) | 3 | 6, 6, 6 | ensemble ambiguous |
| `600519.SH` | `peak-c6c841c136969d7fbfdd` (absent) | 4 | 204, 213, 121, 73 | ensemble ambiguous |

Every symbol enters 2020 with valid active structural episodes but an orphaned
saved base ID. On the 331 non-ensemble-ambiguous dates, lookup cannot find that
ID. On the other 884 dates, the stricter same-day ensemble rule also fails.
This is why every 2020 row is invalid.

### 2020 transition and event counts

`EA` means `ENSEMBLE_PEAK_AMBIGUOUS`; `BL` means
`TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS`.

| Symbol | EA | BL | EA→BL | BL→EA | Split | Merge | Lost | Representative dates |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `000001.SZ` | 152 | 91 | 11 | 10 | 19 | 25 | 29 | ambiguity 01-02; split/merge 01-21; lost 02-12; BL 05-28 |
| `002260.SZ` | 243 | 0 | 0 | 0 | 0 | 0 | 0 | EA for every 2020 observation, starting 01-02 |
| `002706.SZ` | 154 | 89 | 7 | 7 | 13 | 20 | 33 | BL 01-02; ambiguity/lost 01-14; split/merge 01-21 |
| `300604.SZ` | 135 | 108 | 18 | 17 | 25 | 37 | 63 | ambiguity 01-02; merge/lost 01-06; BL 01-14; split 01-15 |
| `600519.SH` | 200 | 43 | 3 | 3 | 9 | 12 | 13 | ambiguity 01-02; BL 01-03; merge/lost 01-16; split 01-23 |

No transition reaches `TRACKED` in 2020.

## Invalid episodes, 2018--2020

An episode is a maximal contiguous run of strict-invalid transition days.
`T` means an effective base existed but a split/merge/lost event still made
the row strict-invalid; `PM`, `EA`, and `BL` have the meanings above. Counts in
the event columns overlap. “New” is the number of distinct ensemble IDs born
inside the episode.

| Symbol | Start | End | Days | State-day counts | EA | No base | Split | Merge | Lost | New | Recovery |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| `000001.SZ` | 2018-01-10 | 2018-01-10 | 1 | BL 1 | 0 | 1 | 1 | 1 | 0 | 0 | TRACKED 2018-01-11 |
| `000001.SZ` | 2018-01-12 | 2020-12-31 | 722 | EA 350, BL 372 | 350 | 722 | 52 | 69 | 83 | 102 | none |
| `002260.SZ` | 2018-01-03 | 2018-06-04 | 100 | PM 100 | 0 | 100 | 0 | 0 | 0 | 0 | TRACKED 2018-06-05 |
| `002260.SZ` | 2018-06-15 | 2018-06-15 | 1 | T 1 | 0 | 0 | 0 | 1 | 1 | 1 | TRACKED 2018-06-19 |
| `002260.SZ` | 2018-06-22 | 2018-06-25 | 2 | T 2 | 0 | 0 | 0 | 2 | 2 | 2 | TRACKED 2018-06-26 |
| `002260.SZ` | 2018-06-29 | 2018-06-29 | 1 | T 1 | 0 | 0 | 0 | 1 | 1 | 1 | TRACKED 2018-07-02 |
| `002260.SZ` | 2018-07-04 | 2020-12-31 | 609 | EA 527, BL 82 | 527 | 609 | 41 | 54 | 62 | 85 | none |
| `002706.SZ` | 2018-01-18 | 2018-01-19 | 2 | T 2 | 0 | 0 | 1 | 2 | 1 | 1 | TRACKED 2018-01-22 |
| `002706.SZ` | 2018-02-12 | 2018-02-12 | 1 | T 1 | 0 | 0 | 1 | 1 | 0 | 1 | TRACKED 2018-02-13 |
| `002706.SZ` | 2018-02-22 | 2018-02-22 | 1 | EA 1 | 1 | 1 | 0 | 0 | 1 | 0 | TRACKED 2018-02-23 |
| `002706.SZ` | 2018-03-05 | 2018-03-07 | 3 | EA 3 | 3 | 3 | 0 | 0 | 2 | 0 | TRACKED 2018-03-08 |
| `002706.SZ` | 2018-03-13 | 2018-03-15 | 3 | T 3 | 0 | 0 | 3 | 3 | 2 | 3 | TRACKED 2018-03-16 |
| `002706.SZ` | 2018-03-20 | 2018-03-20 | 1 | T 1 | 0 | 0 | 0 | 1 | 1 | 0 | TRACKED 2018-03-21 |
| `002706.SZ` | 2018-03-22 | 2018-03-22 | 1 | T 1 | 0 | 0 | 1 | 1 | 0 | 1 | TRACKED 2018-03-23 |
| `002706.SZ` | 2018-03-27 | 2018-03-27 | 1 | EA 1 | 1 | 1 | 0 | 0 | 1 | 0 | TRACKED 2018-03-28 |
| `002706.SZ` | 2018-04-03 | 2018-04-03 | 1 | T 1 | 0 | 0 | 0 | 1 | 1 | 0 | TRACKED 2018-04-04 |
| `002706.SZ` | 2018-05-09 | 2018-05-09 | 1 | T 1 | 0 | 0 | 0 | 0 | 1 | 0 | TRACKED 2018-05-10 |
| `002706.SZ` | 2018-05-11 | 2018-05-11 | 1 | T 1 | 0 | 0 | 0 | 0 | 1 | 0 | TRACKED 2018-05-14 |
| `002706.SZ` | 2018-05-17 | 2018-05-18 | 2 | T 2 | 0 | 0 | 2 | 2 | 1 | 1 | TRACKED 2018-05-21 |
| `002706.SZ` | 2018-05-24 | 2020-12-31 | 637 | EA 295, BL 342 | 295 | 637 | 37 | 51 | 71 | 79 | none |
| `300604.SZ` | 2018-01-04 | 2020-12-31 | 728 | EA 463, BL 265 | 463 | 728 | 110 | 162 | 209 | 279 | none |
| `600519.SH` | 2018-01-11 | 2018-01-11 | 1 | T 1 | 0 | 0 | 0 | 0 | 1 | 0 | TRACKED 2018-01-12 |
| `600519.SH` | 2018-01-16 | 2018-01-17 | 2 | T 2 | 0 | 0 | 1 | 1 | 1 | 0 | TRACKED 2018-01-18 |
| `600519.SH` | 2018-01-24 | 2018-01-25 | 2 | T 2 | 0 | 0 | 1 | 2 | 1 | 0 | TRACKED 2018-01-26 |
| `600519.SH` | 2018-01-29 | 2020-12-31 | 711 | T 1, EA 356, BL 354 | 356 | 710 | 36 | 53 | 60 | 67 | none |

The only nonrecovering episodes are those containing permanent base loss. The
short earlier ambiguity and topology episodes recover when the original base
identity continues unambiguously. Thus:

- `base_lost`: absorbing after the five dates listed above;
- ordinary ambiguity: recoverable;
- ensemble ambiguity: can alternate with BL and is not itself an absorbing
  tracker state, although `002260.SZ` has economic ambiguity on all 243 2020
  days;
- no-base: absorbing after permanent base loss;
- lost-track memory: there is no matching memory of lost tracks; only the
  orphaned `_base_track_id` remains as a permanent tombstone.

## Ensemble ambiguity remains separate

All 884 2020 ensemble-ambiguous rows have active peaks and a daily dominant in
all three local seller models. On 627 rows, all three local dominants are also
individually unambiguous. None has a local `tracked_base_peak`, because each
local tracker has independently suffered the same one-shot-base inheritance
problem. That local inheritance is not what creates the ensemble ambiguity:
`_ensemble_candidates` reads the same-day canonical candidate sets, not the
local base results.

The candidate-level cause counts below overlap:

| Symbol | Ensemble-ambiguous days | Unmatched seller candidate | Non-unique mapping | Score tie | Incomplete anchor coverage |
|---|---:|---:|---:|---:|---:|
| `000001.SZ` | 152 | 116 | 65 | 0 | 152 |
| `002260.SZ` | 243 | 0 | 243 | 0 | 243 |
| `002706.SZ` | 154 | 134 | 16 | 26 | 154 |
| `300604.SZ` | 135 | 106 | 36 | 5 | 135 |
| `600519.SH` | 200 | 189 | 20 | 0 | 200 |

Representative observations:

- `000001.SZ`, 2020-01-02: candidate counts are 5/5/7 for
  ACTIVE_STICKY/DISPOSITION/UNIFORM. ACTIVE_STICKY's lowest peak at 10.7729
  has no DISPOSITION match, so only 4 of 5 anchor peaks form consensus. All
  three models still have active tracks and a dominant near 14.3560.
- `002260.SZ`, 2020-01-02: counts are 8/8/7. Two anchor proposals compete for
  the same DISPOSITION candidate and multiple proposals compete for UNIFORM
  candidates; only 4 of 8 anchor peaks survive. This exact non-unique topology
  persists on all 243 2020 dates.
- `002706.SZ`, 2020-03-02: counts are 5/4/4. The two low ACTIVE_STICKY peaks at
  6.4570 and 7.1710 have no DISPOSITION correspondence, leaving 3 of 5 anchor
  peaks. Every local model still has active tracks and a dominant at 8.1448.

These are legitimate consequences of the frozen exact-three-model one-to-one
rule. The same 884 rows occurred in the rejected year-local artifact and in
the continuous replay, further proving that the count is not created by
temporal state inheritance. No ensemble threshold or consensus rule should be
relaxed.

## Builder continuation contract

### Current defect

`scripts/build_real_chip_year.py::_checkpoint_journal_symbol_worker` creates a
fresh ensemble tracker. `_run_symbol` advances chip state on warmup days, but
constructs projection rows and invokes `day_sink` only when
`fact.target_required` is true. `consume_day` explicitly rejects non-target
days. The tracker therefore begins on 2020-01-02.

The checkpoint schema itself requires four complete scopes in the order
`uniform`, `disposition`, `active_sticky`, `ENSEMBLE`, including each scope's
base ID, active previous peaks, and applied action IDs. The production writer's
`_tracker(feature)` adapter instead reconstructs only the effective ensemble
base visible in one daily feature row, leaves all local scopes and action IDs
empty, and loses even the ensemble tombstone/active peaks when the effective
base is null. There is no production restore path. The prototype demonstrates
the complete state that would be required, but is not the production writer.

### Required state-flow design

The minimal correct contract is:

1. Instantiate or restore one complete ensemble tracker before the first
   governed transition.
2. On every replayable warmup day, advance all three chip models, produce the
   same canonical candidate sets used by output projection, apply the same
   corporate action once, and advance all four tracker scopes. Suppress only
   feature/journal output.
3. On output days, continue those exact chip and tracker instances and emit the
   feature row.
4. At a checkpoint or annual resume boundary, persist and restore every local
   and ensemble `_previous`, `_base_track_id`, `_applied_action_ids`, all peak
   fields and versions, and no inferred substitutes.
5. Require a single-pass-versus-warmup/output-boundary test to match all scope
   state and emitted target rows exactly. A fresh tracker must fail that test.

This can be implemented without changing chip migration, mass, PIT,
corporate-action, execution, ensemble, or strategy-threshold semantics. It
must not be merged alone, because the exact continued V2 result remains
permanently unusable for rolling-base research.

## Required classifications

| Item | Classification | Reason |
|---|---|---|
| Lost A is never a future matching source | **INTENTIONAL SEMANTIC** | Explicit terminal-event rule and existing regression test. |
| New B receives a fresh ID | **INTENTIONAL SEMANTIC** | Deterministic creation path works in synthetic and real replay. |
| One-time `_base_track_id` never promotes B | **INTENTIONAL SEMANTIC** plus **DESIGN LIMITATION** | It is the explicit V2 transition graph, but unsuitable for a rolling base. No post-loss promotion contract exists. |
| Use of that one-time binding as daily panel base | **DESIGN LIMITATION** | It makes all later panel/lifecycle epochs impossible after permanent loss. |
| Year-local tracker initialization | **BUILD CONTINUATION DEFECT** | Calendar year incorrectly changes identity and coverage. |
| Partial checkpoint tracker adapter/no restore | **OBSERVABILITY GAP** and continuation blocker | Complete state exists in memory and is required by schema but is not materialized/restored by production. |
| Dormant `reappear` continuation bit | **OBSERVABILITY GAP** | No runtime state produces it; it must not imply ID reuse. |
| Exact ensemble one-to-one ambiguity | **INTENTIONAL SEMANTIC** | Candidate-level disagreement is real under the frozen rule. |
| Separate lifecycle root, exact retention, and entry memory | **INTENTIONAL SEMANTIC** | Already represented independently and must remain immutable per setup. |
| Core match/split/merge/lost implementation | No **DEFECT** demonstrated | Synthetic and causal evidence agree with encoded rules. |

The desired rolling rule—when and under what stability/ambiguity conditions B
may be promoted—is **UNRESOLVED BY THE CURRENT CONTRACT**. Adding it requires a
design review, semantic/version bump, regression suite, artifact invalidation,
and a new five-symbol replay before any wider build.

## Hard gates

These gates describe validated current production semantics, not a proposed
future rolling-base design.

`YEAR_BOUNDARY_TRACKER_RESET_IS_DEFECT: YES`

`LOST_IDENTITY_REATTACHMENT_REMAINS_FORBIDDEN: YES`

`NEW_TRACK_CAN_BE_BORN_AFTER_PRIOR_BASE_LOSS: YES`

`NEW_TRACK_CAN_BECOME_NEW_ROLLING_BASE: NO`

`TRACKED_BASE_IS_ROLLING_STRUCTURAL_BASE: NO`

`TRACKED_BASE_IS_IMMUTABLE_ROOT_ANCHOR: NO`

`ROOT_ANCHOR_ALREADY_HAS_SEPARATE_LIFECYCLE_REPRESENTATION: YES`

`CONTINUOUS_2018_2020_TRACKING_HAS_NONZERO_VALID_2020_COVERAGE: NO`

`ZERO_LONG_HISTORY_COVERAGE_ROOT_CAUSE_CLASSIFIED: YES`

`CANONICAL_TRACKER_PRODUCTION_SEMANTICS_CHANGED: NO`

`SAFE_TO_IMPLEMENT_CONTINUATION_FIX: NO`

`SAFE_TO_REBUILD_500_FOR_RESEARCH: NO`

## Next safe step

Do not change production code in this audit. Specify and review a new rolling
base episode contract that preserves permanent death of A, forbids
reattachment, defines causal promotion of B without using today's dominant as
a substitute, and keeps an active strategy root tied to A. Version that design
and add failing-then-passing semantic tests. Only then implement both the
rolling-base transition and exact warmup/checkpoint continuation, rerun these
five symbols, and reconsider the continuation and rebuild gates.
