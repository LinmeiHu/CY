# V12 Setup Recall Remediation Design Study

## Executive answer

The current V12 architecture is structurally overcoupled at candidate creation. A unique canonical base is not economically required to record a PIT-safe research opportunity candidate, but V12 makes canonical identity part of `pre_chain_valid`, lifecycle `hard_valid`, and `peak_identity_valid` before accumulation evidence can reach setup creation. This is a conservative safety design at the production lifecycle boundary and temporal confirmation is being used too early for research candidate intake.

The objective is a profitable, testable swing architecture—not maximal reconstruction of launch points. Wave recall is therefore one diagnostic alongside candidate episodes, duration, matched-control cost, chronological enrichment, and dense-label precision. The deliverable is a stable research universe for a controlled `price candidate alone` versus `same candidate + V3 overlay` experiment, not a new production strategy.

Separating the roles recovers the opportunity sample but does not by itself establish a continuation-selection edge. The broad candidate-first intake covers 1,047/1,599 de-duplicated waves (65.5%) versus 1,018/1,599 controls (63.7%), matched lift 1.03. The explicit ambiguity cohort covers 546 waves and 470 controls (lift 1.16), but its modest direction does not satisfy the pre-registered Continuation Study rule.

The profitable-swing objective requires a different controlled experiment: a fixed candidate system that does not consume V3, followed by a comparison of that system alone with the same system plus V3 confirmation, sizing, continuation, and risk overlays. The price-only variants use registered PIT daily inputs and fixed economic definitions, not future wave labels. P&L-suitable candidate universes under the separate pre-registered sample/enrichment rule: P_PRICE_PULLBACK_20.

The authoritative production accumulation score is structurally near-degenerate in this replay, not merely a threshold placed a little too high. Among 27,317 score-stage rows its exact values are `{"0.0":27252,"0.2":6,"0.4":21,"0.6":30,"0.8":7,"1.0":1}`; 65 rows are nonzero and only one equals `1.00`. The 60-session valid-chain warmup zeroes the score after canonical-base interruptions even when individual raw components are true. Base-free recomputation exposes more component variation, but it does not produce stable positive discrimination. The only split-consistent standalone signal found is `ev_sticky_base`, `ev_downside_absorption`; its polarity is inverse/harmful for bullish candidate selection.

## Scope, authority, and prohibited actions

This study descends from authoritative setup-funnel commit `d0a005daf33398d85f14ce1cba722bfc3b13a066` and verifies its result manifest, frozen V3 identity, Reverse Wave V2 labels, lifecycle ledger, registered CY-006 daily input, registered CY-008 minute-daily input, and unchanged production source hashes. It reads 121,251 frozen symbol-days, 121,186 complete T+1 price-label rows, 1,599 de-duplicated waves, and 1,599 exact-date/board matched controls.

No production strategy source, threshold, rolling-base semantic, chip artifact, lifecycle ledger, or production state was modified or rebuilt. No 3,941-symbol build was started. Research variants are static candidate observations only; no authoritative downstream lifecycle outcome is reused after counterfactually changing setup creation, and no hypothetical fill is produced.

## Four roles and the current coupling

| Role | Needs unique canonical root? | V12 behavior | Research design conclusion |
|---|---|---|---|
| Candidate generation | No | Blocked before setup progression when canonical identity/valid chain is unavailable | Carry observation identity, PIT lineage, and explicit temporal state without a root |
| Structural confirmation | No, but valid structure can raise confidence | Embedded in earliest hard validity | Apply after intake; ambiguity remains an observed state, never a fake base |
| Lifecycle anchoring | Yes before anchor-dependent accumulation/breakout monitoring | Bound atomically at `SETUP_OBSERVED` | May occur later than candidate creation, but before selecting support with breakout knowledge |
| Risk/position management | Yes | Exact root retention and deterioration compare to frozen root | Preserve current fail-closed identity and retention semantics |

`cannot bind unique canonical base` is therefore equivalent to `cannot generate any production setup candidate` in current V12, but that equivalence is architectural, not economically required for a research candidate. It remains economically and semantically required before an anchor-dependent production-equivalent lifecycle or trade.

Classification: `OVERCOUPLED_ARCHITECTURE`, `TEMPORAL_CONFIRMATION_USED_TOO_EARLY`, and—at the later production lifecycle boundary—`CONSERVATIVE_DESIGN_CHOICE`.

## Pre-registered architecture comparison

| Architecture | Candidate symbol-days | Episodes | Episodes/symbol-year | Median duration | Waves | Wave recall | Control acceptance | Matched lift | P&L sample sufficient |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `A_CURRENT_V12` | 1 | 1 | 0.00 | 1.0 | 0 | 0.0% | 0.0% | nan | NO |
| `B_CANDIDATE_FIRST` | 88,695 | 561 | 1.12 | 184.0 | 1,047 | 65.5% | 63.7% | 1.03 | NO |
| `P_PRICE_ONLY_BROAD` | 89,356 | 563 | 1.13 | 184.0 | 1,055 | 66.0% | 64.4% | 1.03 | NO |
| `P_PRICE_PULLBACK_20` | 47,518 | 5,671 | 11.34 | 4.0 | 929 | 58.1% | 42.3% | 1.37 | YES |
| `P_PRICE_PULLBACK_STABILIZING` | 19,595 | 12,372 | 24.74 | 1.0 | 8 | 0.5% | 12.5% | 0.04 | NO |
| `C_TEMPORAL_STATE_STRATIFIED` | 88,695 | 561 | 1.12 | 184.0 | 1,047 | 65.5% | 63.7% | 1.03 | NO |
| `C_ENSEMBLE_AMBIGUOUS` | 41,479 | 9,671 | 19.34 | 2.0 | 546 | 34.1% | 29.4% | 1.16 | NO |
| `C_PERSISTENT_AMBIGUITY_20` | 57,090 | 1,113 | 2.23 | 35.0 | 706 | 44.2% | 38.5% | 1.15 | NO |
| `D_ANY_1_BASE_FREE_COMPONENT` | 67,296 | 10,358 | 20.72 | 2.0 | 608 | 38.0% | 43.5% | 0.87 | NO |
| `D_ANY_2_BASE_FREE_COMPONENTS` | 32,479 | 10,817 | 21.63 | 1.0 | 215 | 13.4% | 17.3% | 0.78 | NO |
| `D_ANY_1_PLUS_AMBIGUITY` | 31,461 | 10,974 | 21.95 | 2.0 | 311 | 19.4% | 19.8% | 0.98 | NO |
| `D_ANY_1_PLUS_VALID_BASE` | 20,528 | 6,859 | 13.72 | 2.0 | 174 | 10.9% | 15.6% | 0.70 | NO |

Variant A is the immutable production baseline. Variant B is broad candidate intake after a 60-session base-free-valid chain. Variant C carries one of six explicit temporal states. Variant D recomputes only exact observable component predicates on `RESEARCH_BASE_FREE_CHAIN_V1`; it is not the production panel or score. `ev_sticky_base` remains missing unless unique identity exists at T and T−20.

Variant P is deliberately V3-independent. `P_PRICE_ONLY_BROAD` is an eligibility universe rather than a swing trigger. `P_PRICE_PULLBACK_20` uses a fixed 5% drawdown from the trailing 20-session economic-price high, and `P_PRICE_PULLBACK_STABILIZING` adds a same-day nonnegative price change. These boundaries were specified before evaluation and were not tuned on the 1,599 waves. Episode duration is retrospective reporting only and never a candidate input.

The broad intake's false-positive cost is 1,018 accepted matched controls (63.7%) and 88,695 candidate symbol-days. This is too broad to be a useful selection architecture by itself. Component conjunctions reduce volume but do not yield stable positive enrichment.

## Temporal-state outcomes

| Explicit state | Wave prevalence | Control prevalence | Matched lift | Dense subsequent-wave rate | Lift over eligible base |
|---|---:|---:|---:|---:|---:|
| `VALID_CANONICAL_BASE` | 29.0% | 34.2% | 0.85 | 24.3% | 0.92 |
| `ENSEMBLE_AMBIGUOUS` | 51.4% | 47.8% | 1.07 | 26.5% | 1.00 |
| `NO_CANONICAL_BASE` | 0.0% | 0.0% | nan | — | nan |
| `SPLIT` | 6.5% | 5.1% | 1.27 | 31.0% | 1.17 |
| `MERGE` | 1.6% | 2.5% | 0.65 | 27.2% | 1.03 |
| `LOST/TRANSITION` | 11.4% | 10.3% | 1.11 | 28.9% | 1.09 |

State precedence is `SPLIT`, `MERGE`, `LOST/TRANSITION`, `ENSEMBLE_AMBIGUOUS`, `VALID_CANONICAL_BASE`, then `NO_CANONICAL_BASE`; disruptive identity events are never hidden by an ambiguity label. A candidate in `ENSEMBLE_AMBIGUOUS` has `canonical_base = null`.

### Ensemble ambiguity

| Split | Wave prevalence | Matched-control prevalence | Ratio |
|---|---:|---:|---:|
| Discovery | 65.5% | 64.1% | 1.02 |
| Validation | 66.7% | 53.4% | 1.25 |
| Holdout | 66.3% | 62.7% | 1.06 |

Exact `ENSEMBLE_PEAK_AMBIGUOUS` direction is positive in all chronological splits, consistent with the predecessor study, but effect size is regime-dependent. The mutually exclusive `ENSEMBLE_AMBIGUOUS` temporal-state stratum is smaller because `SPLIT`, `MERGE`, and `LOST/TRANSITION` take explicit precedence. Trailing persistence and current episode age are PIT-usable. Full episode duration and resolution time are reported only as retrospective outcomes and are forbidden candidate inputs.

The seller-model configuration is `UNIFORM,DISPOSITION,ACTIVE_STICKY`. The frozen daily fact exposes aggregate p50/p90/peak disagreement spreads, not each model's independently defined peak/band geometry. Because chip rebuilds are prohibited, independent per-model geometry is explicitly unidentifiable rather than reconstructed or substituted.

## Accumulation score diagnosis

Production `setup_score` is the five-component arithmetic mean, but the accepted `>= 1.00` boundary is exactly a five-way conjunction. The distribution is dominated by `0.0` because:

1. canonical identity is part of the valid-chain epoch;
2. every invalid/ambiguous observation resets that epoch;
3. `observation_from_record` forces score `0.0` until 60 valid-chain observations accrue; and
4. the component conjunction is rare even after eligibility.

This is a structural near-degeneracy caused by eligibility, warmup, conjunction, and scaling together. It also lacks wave/control discrimination. That diagnosis does not justify changing the production threshold.

## Research-only component model

| Component | Dependency | Wave availability | Wave prevalence | Control prevalence | Lift | Classification |
|---|---|---:|---:|---:|---:|---|
| `ev_turnover_absorption` | BASE_FREE_OBSERVABLE | 1047/1599 | 9.9% | 10.2% | 0.98 | NEUTRAL_OR_DIRECTIONALLY_UNSTABLE |
| `ev_near_price_chip_growth` | BASE_FREE_OBSERVABLE | 1047/1599 | 7.4% | 9.8% | 0.76 | NEUTRAL_OR_DIRECTIONALLY_UNSTABLE |
| `ev_concentration_improves` | BASE_FREE_OBSERVABLE | 1047/1599 | 25.6% | 26.9% | 0.95 | NEUTRAL_OR_DIRECTIONALLY_UNSTABLE |
| `ev_sticky_base` | REQUIRES_UNIQUE_CANONICAL_TRACK_AT_T_AND_T_MINUS_20 | 145/1599 | 4.9% | 8.6% | 0.57 | INFORMATIVE_INVERSE_HARMFUL_AS_BULLISH_EVIDENCE |
| `ev_downside_absorption` | BASE_FREE_OBSERVABLE | 1047/1599 | 10.1% | 19.1% | 0.53 | INFORMATIVE_INVERSE_HARMFUL_AS_BULLISH_EVIDENCE |

The four base-free components use the exact authored Boolean predicates but a separately named base-free-valid rolling chain. `ev_sticky_base` is unavailable without unique temporal identity. Missing components remain null; they are never coerced into a fake positive or a fabricated production score.

Discovery did not identify a positive standalone component eligible for promotion into a discovery-selected optimized score. The study therefore evaluates only the fixed, interpretable `any 1`, `any 2`, accumulation-plus-ambiguity, and accumulation-plus-valid-base diagnostics predeclared above. Holdout is never used for feature selection.

## Root-anchor boundary

A root can be bound later than research candidate creation. It must be frozen no later than promotion into an anchor-dependent production-equivalent accumulation/breakout lifecycle. Waiting until after breakout selection would allow future price action to influence root choice; executing or evaluating retest/root retention without a root would be semantically invalid. The machine-readable stage audit is `root_anchor_boundary_audit.csv`.

## Statistical protocol and researchability

Splits are chronological: discovery through 2020-04-30, validation from 2020-05-01 through 2020-08-31, and holdout from 2020-09-01. Waves are price-only de-duplicated events. Controls are exact-date/board matched, union-upside-negative, and separated from the same symbol's selected waves. Wilson and deterministic symbol-cluster bootstrap intervals are reported.

Before holdout evaluation, a researchable continuation architecture was required to have at least 100 candidate waves and 25% wave recall in both validation and holdout, matched lift at least 1.10 in both, and a conservative pooled out-of-sample cluster lower bound above 1.00. Passing architectures: P_PRICE_PULLBACK_20, C_PERSISTENT_AMBIGUITY_20.

The separate P&L-study gate preserves that safeguard and asks a narrower question: is there a V3-independent swing universe with at least 500 total episodes, at least 100 episode onsets and 100 covered waves in each out-of-sample period, median duration of 1–20 sessions, and modest matched lift of at least 1.05 in both validation and holdout? Passing architectures: P_PRICE_PULLBACK_20. This gate authorizes only the design/run of a controlled P&L research study; it does not validate profitability or production deployment.

Candidate counts and replicated enrichment are now large enough for a statistically powered future Continuation Study: P_PRICE_PULLBACK_20, C_PERSISTENT_AMBIGUITY_20. This study does not claim that continuation/exit effects are already identified, because it deliberately creates no hypothetical anchored breakout lifecycle. A P&L-oriented candidate-alone versus candidate-plus-V3 comparison is safe to run, without starting it automatically.

## Required answers

1. **Is unique canonical-base availability economically required before candidate generation?** No. It is required before anchor-dependent lifecycle promotion, not before recording a PIT-safe research candidate.
2. **Is temporal confirmation currently being applied too early?** Yes, for candidate intake; no weakening is justified at the later root-dependent production boundary.
3. **Can ambiguity be an explicit candidate state without inventing a base?** Yes. Store `temporal_state=ENSEMBLE_AMBIGUOUS` and `canonical_base=null`.
4. **Does candidate-first architecture recover substantial wave recall?** Yes: 1,047/1,599 (65.5%) versus 0/1,599 in Variant A.
5. **What is the control false-positive cost?** 1,018/1,599 matched controls (63.7%) plus 88,695 broad candidate symbol-days.
6. **Does any candidate architecture replicate enrichment out of sample?** Yes. `P_PRICE_PULLBACK_20` and `C_PERSISTENT_AMBIGUITY_20` meet the pre-registered continuation-candidate criterion; broad Variant B alone does not.
7. **Is the current accumulation score structurally degenerate or merely conservative?** Structurally near-degenerate in this replay; the canonical-chain warmup and five-way conjunction collapse nearly all values to zero.
8. **Which components contain standalone information?** `ev_sticky_base`, `ev_downside_absorption`; the replicated information is inverse/harmful under the authored bullish polarity. No stable positive component is found.
9. **When should immutable root binding occur?** After research candidate creation but before promotion into anchor-dependent accumulation/breakout monitoring, and necessarily before retest, entry, or retention logic.
10. **Can the funnel support a statistically identifiable Continuation Study?** Yes as a candidate universe. Continuation outcomes still require the next separately governed lifecycle/P&L experiment; none are fabricated here.

## Hard gates

`CURRENT_SETUP_ARCHITECTURE_CLASSIFICATION: OVERCOUPLED_ARCHITECTURE; TEMPORAL_CONFIRMATION_USED_TOO_EARLY; CONSERVATIVE_DESIGN_CHOICE_AT_ROOT_DEPENDENT_BOUNDARY`

`UNIQUE_CANONICAL_BASE_REQUIRED_FOR_CANDIDATE_GENERATION: NO`

`TEMPORAL_CONFIRMATION_APPLIED_TOO_EARLY: YES`

`AMBIGUITY_CAN_BE_EXPLICIT_CANDIDATE_STATE: YES`

`CURRENT_ACCUMULATION_SCORE_DEGENERATE: YES`

`INFORMATIVE_ACCUMULATION_COMPONENTS_FOUND: YES`

`CANDIDATE_FIRST_RECALL_IMPROVES: YES`

`CANDIDATE_FIRST_ENRICHMENT_VALIDATES: NO`

`ROOT_ANCHOR_CAN_BE_BOUND_LATER_THAN_CANDIDATE_CREATION: YES`

`RESEARCHABLE_CONTINUATION_FUNNEL_IDENTIFIED: YES`

`PRODUCTION_THRESHOLD_CHANGE_JUSTIFIED: NO`

`PRODUCTION_TEMPORAL_SEMANTICS_CHANGE_JUSTIFIED: NO`

`SAFE_TO_DESIGN_NEW_SETUP_ARCHITECTURE: YES`

`SAFE_TO_IMPLEMENT_NEW_SETUP_ARCHITECTURE: NO`

`SAFE_TO_START_FULL_MARKET_3941_BUILD: NO`

`SAFE_TO_RUN_PNL_ORIENTED_SWING_STUDY: YES`
