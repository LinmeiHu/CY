# Data audit

## Status at research start

The repository safety gate passed on 2026-08-30:

- repository: `/Users/linmei/Documents/CY-supermind-v6`;
- branch: `research/chinext-v1`;
- starting HEAD: `e361aa9fb9`;
- worktree: clean;
- no branch switch, reset, clean, checkout overwrite, rebase, deletion, or replay
  mutation was performed.

## Authoritative artifacts found

| Period | Data/universe grade | Baseline output | Frozen result summary |
|---|---|---|---|
| 2018-2021 | bounded effective-state PIT-B; not strict PIT-A | `output/chinext_v1_extended_2018_2021/` | `reports/chinext_v1_extended_replay_summary.json` |
| 2022-2023 | CY-028 bounded reconstructed PIT-B; not strict PIT-A | `output/chinext_v1_phase9b_oos/O0_BASELINE/` | `reports/chinext_v1_phase9b_oos_validation_summary.json` |
| 2024-2025 | CY-027 bounded reconstructed PIT-B; not strict PIT-A | `output/chinext_v1_pit_replay/` | `reports/chinext_v1_pit_replay_summary.json` |

All three bind the same authoritative strategy SHA-256
`dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`.

## Frozen ledger hashes verified at start

| Block | Daily NAV | Event ledger | Execution ledger |
|---|---|---|---|
| 2018-2021 | `4794fe7877adb4ac912e8def90d8b46cc4e3d213c1c40cc567860e98a799901a` | `9fb92730ca1c30e448b32b07b6c5ab369b178c820821daf21f3b69b90b0dfc86` | `878e5d52661323507d62ae5d72bcf8f050d005f8c64a631ab6fb5ae59b7bd249` |
| 2022-2023 O0 | `1ff55ee194bbdc5fcb4c6041d99dbe5335548a22f05877aa17dc79fbe7152aa8` | `ea2200e87ada0bc9a2b5ddcf7b9426c7bdfba20befc9cf58a802233fa5cef50c` | `c83f6199984a30876bd6efc1b8cf3056b9073bfa4fce0380dab9d75235bdf0bf` |
| 2024-2025 | `a1b8399c7f199a76ae6e891bbd690de16a3312d2cc548c77d552f2531adcc071` | `721bdaa57e701ce40a9be37c29b6f0a13427efaf9074682bfc79255a4e62f655` | `f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5` |

## Known limitations that remain active

1. All membership blocks are PIT-B, not strict archival PIT-A. BaoStock historical
   record-level `available_at` and supplier revision-vintage chains are unavailable.
2. Existing 2018-2025 outcomes have already been viewed; there is no untouched
   historical OOS block for a newly invented V1-R.
3. The three NAV blocks start independently. They support yearly and blockwise
   comparisons, not a silently chained eight-year portfolio claim.
4. CY-006 `is_st` coverage is incomplete for some earlier CY-027/CY-028 contracts;
   the exact bounded validation/authorization limitations remain in force.
5. Execution is a partial research model: open-limit/trading-state/T+1 checks are
   enforced, but order-book queue, impact, and realized slippage are not modeled.
6. Existing breadth is available for 2022-2025 from exact PIT membership, with a
   95% coverage rule and substantial warmup-related invalidity for MA60/B60 early
   in the sample. No silent imputation is allowed.
7. Industry/style classification inputs require exact registered PIT lineage.
   Existing reports classify industry incrementality as unresolved/inconclusive;
   no current classification may be backfilled.
8. Exact 399102.SZ is the only regime anchor permitted. Its completed-bar
   availability convention must be preserved and never turned into same-day fill.

## Completed lineage and coverage audit

- Phase 0 verified all nine authoritative NAV/event/execution hashes and all six
  frozen identity/economic gates for each independently bounded block without a
  formal baseline replay.
- Phase 2 built 93 outcome-blind daily features on all 1,942 sessions. Exact
  `basic_eligible` counts match authoritative ledgers on 1,942/1,942 dates. The
  deterministic feature artifact SHA-256 is
  `5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6`.
- Cross-sectional features require at least 100 contemporaneously eligible names
  and fail closed on 184 sessions. For deployable raw MA20 breadth, valid coverage
  is only 53.5% in 2018 and 75.6% in 2022; no value was imputed.
- Trend, index volatility, and observed relative-index features have complete
  daily coverage. Growth/value, true PIT market-cap style, fund flow/sentiment,
  and governed cyclical classifications are `UNAVAILABLE`, not proxy-substituted.
- CY-030/CY-031/CY-032 are narrowly bounded Phase 7 research assets for the exact
  existing PIT-B artifacts and frozen candidate code. They authorize neither
  current-survivor fallback, strict PIT-A claims, optimization, nor production.
- The Phase 7 candidate outputs are isolated from authoritative V1. A frozen
  identity manifest rehashes all 15 arm ledgers; the Phase 8/9 audit found zero
  same-day fills, timestamp/first-applicable failures, missing-input candidate
  buys, target-weight mismatches, or signal/rank/exit changes.

## Isolated-worktree input restoration and EXP-WLA-001 audit

The dedicated worktree initially lacked six Git-ignored but hash-bound input
artifacts. Before preregistration, the following source bytes were copied into the
isolated worktree and rehashed exactly: CY-028 membership `1af35779...`, CY-027
membership `9a6a0a07...`, extended historical state `995cdbcc...`, extended
security master `ff709212...`, official-document index `92b59450...`, and exact
399102 anchor `e096e4d5...`. No output ledger, source-worktree modification, or
external `opportunity_conversion/` file was imported.

An outcome-blind audit read only trade IDs, symbols, blocks, and entry-signal
dates. For every one of 399 cycles and every fixed anchor T-60/T-40/T-20/T-10/
T-5/T-3/T-1, all 21 required rows exist, all are hard-valid, and all 20 causal
corporate-action coordinate steps are contiguous. The accepted extended
transient canonical and membership hashes remain `07b2f8ea...` and `c4e89c4e...`.
No outcome column was read during this availability audit.

The subsequent EXP-ICD-001 industry audit was also outcome-blind. All 399 entry
securities have a source-notice-valid industry label and exact own ret20/ret60.
There are 68 contemporaneous labels. Excluding the entry security, 367 entries
have at least one valid peer and the fixed >=5-peer rule admits 296 entries in
both horizons (136/194 EXTENDED, 67/94 HOLDOUT, 93/111 DEVELOPMENT). Entry-date
eligible-universe industry mapping coverage is 100%; peer count has minimum 0,
median 11, maximum 62. No outcome was read before freezing the >=5 rule.

EXP-PEL-001's availability-only audit reads only null/not-null status from the
already accepted Phase 1 path columns: 295/399 trades have return5, 192/399 have
return10, and 91/399 have return20. Counts by EXTENDED/HOLDOUT/DEVELOPMENT are
137/59/99, 92/35/65, and 47/10/34 respectively. All 399 signal dates precede
execution dates. No path value or terminal outcome was inspected before day 5
was frozen as the sole primary landmark.

EXP-EOS-001's availability/semantics audit finds 399/399 non-null, finite
accepted values for holding duration, MFE, MAE, days-to-MFE, days-to-MAE, and
canonical exit reason. Phase 1 constructs zero-based coordinates over the held
path from entry execution through exit execution inclusive; Python max/min over
chronological tuples retains the first occurrence on an exact tie. No excursion
order was calculated before its primary orientation and gates were frozen.

EXP-FBB-001's outcome-blind boundary audit finds 121 MFE-at-entry, 88
MAE-at-entry, 3 MFE-at-exit, and 24 MAE-at-exit paths. The frozen directional
boundary-clean rule (exclude MFE-at-entry and MAE-at-exit) admits 265/399 cycles;
requiring both extrema strictly inside the path admits 179/399. These counts were
frozen without reading the false-breakout endpoint.

EXP-EGP-001's outcome-blind entry audit binds the three accepted execution
ledgers at their baseline-manifest hashes. Their 409 entry fills join 399/399
completed cycles; the ten unmatched development entries are the already-known
terminal open cycles. All 399 signal/execution bars are hard-valid, have one exact
T+1 action-safe coordinate step, match ledger execution open exactly, and cover
399102 signal close/execution open. Execution price equals execution open for all
399, so intraday fill premium has no variation. No gap value was calculated
before the stock-minus-market feature and gates were frozen.
