# V12 Setup / Accumulation Funnel Root-Cause Study

## Executive answer

The production funnel is reconstructed authoritatively from the immutable 121,251-row frozen V3 fact and its already-built lifecycle ledger. No chip, panel, ledger, strategy state, threshold, or production source was rebuilt or changed.

Only one production setup was created because setup creation requires two rare conditions in sequence:

1. a fail-closed lifecycle-valid observation with a current canonical unambiguous tracked base; and
2. an accumulation score of exactly `1.00`, which is equivalent to all five Boolean accumulation components being true on the same observation.

Across the 1,599 exact Reverse Wave V2 pre-start observations, the authoritative first blocker is `hard_valid` for 1,225 (76.6%), `setup_score` for 373 (23.3%), and `tradable` for 1. The `hard_valid` name is composite: 1,057 waves (66.1%) were in exact `ENSEMBLE_PEAK_AMBIGUOUS` state, and 1,085 (67.9%) lacked a valid production peak identity. Thus the dominant authoritative predicate is lifecycle `hard_valid`, while its dominant nested cause is unavailable/ambiguous canonical rolling-base identity.

This is not evidence that all 1,599 price waves were desirable trades. It is exact price-opportunity recall of zero, not a strategy-quality verdict. Exact-date/board matched controls show that ambiguity is more common before waves in discovery, validation, and holdout, so the fail-closed ambiguity restriction removes winners at least as aggressively as controls; however, removing it would change rolling windows and lifecycle state, making downstream setup/entry performance unidentifiable from this immutable replay.

## Governed baseline and PIT contract

| Item | Identity |
|---|---|
| Completed Reverse Wave V2 commit | `b59b1adde6ba43929f9ad20a533f296d610755dd` |
| Frozen root manifest | `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a` |
| Freeze lock | `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9` |
| Ledger manifest | `4b4ba0325f41dfcda5f9a7e8e3f259907dbf596f5b2863f622bf2503c7e30254` |
| Ledger implementation commit | `3488a95dfb17815e7ea23f065c702106dcd10437` |
| Accepted parameter ID | `9baed76ec299161c` |
| Feature rows / symbols | 121,251 / 500 |
| Wave events / matched controls | 1,599 / 1,599 |

Wave observations use Reverse Wave V2 feature date T, whose authoritative availability precedes the price-defined event start T+1. Controls are selected without chip or strategy outcomes: union-upside-negative observations matched one-for-one on exact feature date and board, without replacement within each stratum, and more than ten feature sessions from any selected wave for the control symbol. Splits remain chronological; no row is randomly shuffled across time.

## Exact production setup path

The complete machine-readable execution order is `results/setup_path_catalog.csv`. The crucial source semantics are:

- `panel._create_panel_table` constructs `pre_chain_valid`. It requires PIT/input/action/mass/known-cost validity plus a current peak ID, no ambiguity/split/merge/loss, and exact peak versions. It then sets `research_hard_valid = pre_chain_valid`.
- `signals.observation_from_record` forms lifecycle `hard_valid = research_hard_valid AND profile_valid AND peak_valid`, then fails it closed on missing actionable positive fields or missing `known_cost_fraction_min`. If the valid-chain `history_count` is below the 60-session accumulation window, it forces setup score to `0.0`.
- `LifecycleMachine.advance` checks corporate action, lifecycle `hard_valid`, and current `peak_identity_valid`; rebases memory; routes any active signal away from setup creation; requires tradability, zero cooldown, and state `NEUTRAL` or `BROKEN`; compares `setup_score >= 1.00`; then freezes the root anchor and enters `ACCUMULATING`.
- There is no direct `peak_track_age` minimum. Persistence enters through `ev_sticky_base`, which requires the same track ID at T and T−20, recent band overlap at least `0.55`, and p50 movement within one ATR.
- Seller-model disagreement is not a setup gate. It is checked downstream in breakout/retest qualification.

Later state-machine predicates are not evaluated after a blocking failure. Panel quantities already computed on a rejected row remain observable, but they are not promoted to counterfactual lifecycle decisions.

## Canonical 1,599-wave funnel

| Order | Actual authoritative stage | Survivors | Recall | Eliminated at stage |
|---:|---|---:|---:|---:|
| 0 | `authoritative_observation` | 1,599 | 100.0% | 0 |
| 1 | `corporate_action_clear` | 1,599 | 100.0% | 0 |
| 2 | `lifecycle_hard_valid` | 374 | 23.4% | 1,225 |
| 3 | `peak_identity_valid` | 374 | 23.4% | 0 |
| 4 | `tradable` | 373 | 23.3% | 1 |
| 5 | `neutral_or_broken_and_no_cooldown_setup_score_evaluated` | 373 | 23.3% | 0 |
| 6 | `setup_score_ge_1_00` | 0 | 0.0% | 373 |
| 7 | `setup_created` | 0 | 0.0% | 0 |

The apparent zero incremental loss at `peak_identity_valid` is not evidence that peak identity is harmless: lifecycle `hard_valid` already embeds peak validity and the stricter split/merge/lost restrictions. The overlap is exposed in `wave_funnel.csv`, not double-attributed.

At T before launch, 514 waves had a current canonical base, 464 were strict temporal-valid, and only 160 had the same canonical base ID at T and T−20. Production imposes no direct peak-age threshold; the T−20 identity is only one operand inside `ev_sticky_base`. 1,085 waves had no usable production peak identity. Of the 373 waves that reached the accumulation-score gate, none passed `1.00`.

### Matched-control survival

| Actual cumulative stage | Wave recall | Control acceptance | Wave incremental pass | Control incremental pass | Incremental enrichment |
|---|---:|---:|---:|---:|---:|
| `authoritative_observation` | 100.0% | 100.0% | 100.0% | 100.0% | 1.00 |
| `corporate_action_clear` | 100.0% | 99.9% | 100.0% | 99.9% | 1.00 |
| `lifecycle_hard_valid` | 23.4% | 27.2% | 23.4% | 27.2% | 0.86 |
| `peak_identity_valid` | 23.4% | 27.2% | 100.0% | 100.0% | 1.00 |
| `tradable` | 23.3% | 26.8% | 99.7% | 98.4% | 1.01 |
| `neutral_or_broken_and_no_cooldown_setup_score_evaluated` | 23.3% | 26.8% | 100.0% | 100.0% | 1.00 |
| `setup_score_ge_1_00` | 0.0% | 0.0% | 0.0% | 0.0% | — |
| `setup_created` | 0.0% | 0.0% | — | — | — |

The balanced matched-sample precision and Wilson intervals are in `wave_vs_control_gate_comparison.csv`. The same table includes 300-draw symbol-cluster bootstrap intervals for wave and control pass rates in total and in every chronological split. In total, the lifecycle-valid cumulative gate retains controls more often than waves, so the dominant validity restriction does not enrich for the price-wave outcome.

## Explicit validity audit

The raw frozen feature `hard_valid` and production lifecycle `hard_valid` are different fields with different semantics:

- frozen `research_valid`: 120,472 pass / 779 fail; it feeds the adapted panel;
- frozen `hard_valid`: 0 pass / 121,251 fail;
- raw `UNKNOWN_COST_PRESENT`: present on all 121,251 rows;
- bounded `known_cost_fraction_min`: available on all 121,251 rows;
- production lifecycle `hard_valid`: 27,736 pass / 93,515 fail;
- production `peak_identity_valid`: 41,619 pass / 79,632 fail;
- current strict temporal-valid: 36,219 pass / 85,032 fail.

The adapter deliberately maps frozen `research_valid` to `chip_input_valid` and `state_chain_valid`; it does not use frozen `hard_valid`. Production consumes the bounded known-cost fraction and fails only when it is missing. Therefore `UNKNOWN_COST_PRESENT` is descriptive lineage state, not the direct setup blocker in this replay. Full expressions and evaluated/not-evaluated counts are in `validity_gate_audit.csv`.

## Accumulation decomposition

The score is the exact arithmetic mean of five Boolean components. At the accepted threshold `>= 1.00`, it is a five-way conjunction.

| Component | Wave rows evaluated | Wave true | Control rows evaluated | Control true |
|---|---:|---:|---:|---:|
| `ev_turnover_absorption` | 373 | 48 (12.9%) | 428 | 43 (10.0%) |
| `ev_near_price_chip_growth` | 373 | 2 (0.5%) | 428 | 4 (0.9%) |
| `ev_concentration_improves` | 373 | 13 (3.5%) | 428 | 21 (4.9%) |
| `ev_sticky_base` | 373 | 19 (5.1%) | 428 | 40 (9.3%) |
| `ev_downside_absorption` | 373 | 73 (19.6%) | 428 | 159 (37.1%) |

Globally, 27,317 rows reached the score stage; only one passed. The score-stage distribution has median 0.0, 95th percentile 0.0, and maximum 1.0. The exact distributions for all rows, wave observations, matched controls, and conditional score-stage rows are in `accumulation_score_distribution.csv`.

Component flags are panel evidence, while the compared score is the exact lifecycle observation value. During the 60-session valid-chain warmup, `observation_from_record` forces that score to `0.0` even if one or more raw component flags are true; the component table therefore must not be read as a recomputed counterfactual score.

The threshold is the terminal bottleneck conditional on reaching the setup-capable state, but it is not the dominant first blocker across waves: 1,225 waves disappear earlier at lifecycle `hard_valid`. Discovery coverage diagnostics find that the score threshold needed to cover 80%, 90%, or 95% of discovery waves is `0.0` because of the mass at zero; that accepts essentially all controls and does not validate discrimination. This is a diagnostic, not a recommendation.

## Ensemble ambiguity: direction and role

| Split | Wave `ENSEMBLE_PEAK_AMBIGUOUS` | Matched control | Difference |
|---|---:|---:|---:|
| Discovery | 65.5% | 64.1% | +1.4% |
| Validation | 66.7% | 53.4% | +13.3% |
| Holdout | 66.3% | 62.7% | +3.6% |

The direction replicates: ambiguity is more prevalent before waves in all three chronological splits. Twenty-session ambiguity persistence is also analyzed in `ensemble_ambiguity_audit.csv`. This means `ENSEMBLE_AMBIGUITY_HAS_INFORMATION: YES` points toward later-wave association, not bearish selection. Production blocks the underlying `peak_track_ambiguous` state through `pre_chain_valid` and `peak_identity_valid`; the named ensemble state is descriptive but coincides with 1,057 wave rejections.

This association does not justify relaxing consensus. It may reflect seller-model disagreement near transitions, but the frozen artifacts do not identify that mechanism causally.

## Setup semantics and lifecycle occupancy

There is no hidden cooldown, one-shot, or stale-terminal suppressor:

- no `cooldown_complete` rejection was emitted;
- no active signal or holding interval existed;
- one setup was created for `000709.SZ` on 2020-12-18;
- it remained `ACCUMULATING` through 2020-12-31, with 9 observed breakout rejections, and the sample ended before expiry;
- all other symbols created no lifecycle.

The one setup is not an absorbing-state defect. It is the only observation where all prior gates and all five setup components passed. The state machine then behaved as authored.

Classification: `OVERLY_SELECTIVE_BUT_INTENTIONAL` for the exact-conjunction setup semantics; `TEMPORAL_REPRESENTATION_LIMITATION` for the dominant absence/ambiguity of a usable canonical base; no implementation defect found.

## Counterfactual limits and downstream thresholds

A one-row threshold relaxation can be measured only as static sensitivity. Allowing rows rejected solely by `setup_score` to continue would create new anchors and persistent lifecycle state, so later breakouts/retests/entries cannot be inferred without mutating the state machine. Likewise, removing ambiguity changes valid-chain epochs, rolling evidence, anchors, and occupancy. Those downstream states are unidentifiable here.

The accepted parameters remain unchanged. Setup score is weakly estimable (one pass); breakout excess is weakly estimable (nine observations, all failed); retest depth, cost migration, volume ratio, turnover ratio, and root retention are unidentifiable because they were never reached. See `downstream_threshold_audit.csv`.

## Answers to the required questions

1. **Why only one setup and zero entries?** Most observations fail lifecycle validity/current canonical base. Among 27,317 score-stage rows globally, only one satisfies all five components; it never breaks out, so no downstream entry path exists.
2. **Where do most waves disappear?** At authoritative lifecycle `hard_valid`: 1,225/1,599.
3. **Dominant data-validity condition?** The named first blocker is a validity gate, but its dominant nested cause is temporal peak/base ambiguity, not raw unknown-cost status.
4. **Dominant temporal/rolling-base availability blocker?** Yes: 1,085 waves lack production peak identity, predominantly ensemble ambiguity.
5. **Is ensemble ambiguity dominant?** Yes as the largest nested observable cause (1,057); it is also more prevalent among waves than matched controls in every split.
6. **Is accumulation `1.00` dominant?** No across all waves; yes as the terminal bottleneck conditional on reaching its stage. It shows no validated event/control discrimination.
7. **Is a setup state-machine predicate dominant?** No. Active lifecycle and cooldown do not explain suppression.
8. **Implementation defect?** No source/state evidence supports one.
9. **Would removing the dominant blocker improve downstream discrimination?** Not established. Downstream states become counterfactual and the observable ambiguity association points in the wrong direction for a winner-excluding gate.
10. **Can the current architecture support a statistically testable continuation/exit strategy without semantic redesign?** No. One setup, zero breakouts, and zero entries provide no estimable continuation/exit sample.

## Deliverables and reproducibility

The runner is `run_setup_accumulation_funnel.py`; focused regressions are in `test_setup_accumulation_funnel.py`. `results/manifest.json` binds all inputs, authoritative source hashes, row counts, study contracts, hard gates, and SHA-256 hashes for every machine-readable result.

## Hard gates

`SETUP_FUNNEL_RECONSTRUCTED_AUTHORITATIVELY: YES`

`1599_WAVES_FIRST_BLOCKER_ATTRIBUTED: YES`

`MATCHED_CONTROL_FUNNEL_COMPLETE: YES`

`DOMINANT_BLOCKER: LifecycleObservation.hard_valid (principally unavailable/ambiguous canonical peak identity)`

`DOMINANT_BLOCKER_CLASSIFICATION: TEMPORAL_REPRESENTATION_LIMITATION`

`HARD_VALID_IS_SETUP_BLOCKER: YES`

`UNKNOWN_COST_IS_SETUP_BLOCKER: NO`

`TEMPORAL_VALIDITY_IS_DOMINANT_BLOCKER: YES`

`ROLLING_BASE_AVAILABILITY_IS_DOMINANT_BLOCKER: YES`

`ENSEMBLE_AMBIGUITY_IS_DOMINANT_BLOCKER: YES`

`ACCUMULATION_SCORE_1_00_IS_DOMINANT_BLOCKER: NO`

`SETUP_STATE_MACHINE_IS_DOMINANT_BLOCKER: NO`

`IMPLEMENTATION_DEFECT_FOUND: NO`

`WAVE_RECALL_FAILURE_ROOT_CAUSE_IDENTIFIED: YES`

`EXISTING_DOWNSTREAM_THRESHOLDS_IDENTIFIABLE: PARTIAL`

`SAFE_TO_DESIGN_SETUP_RECALL_REMEDIATION: NO`

`SAFE_TO_CHANGE_ACCUMULATION_THRESHOLD: NO`

`SAFE_TO_PROCEED_TO_STRATEGY_REDESIGN: NO`

`SAFE_TO_START_FULL_MARKET_3941_BUILD: NO`
