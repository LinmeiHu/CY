# Reverse Wave Study V2

## Executive result

Reverse Wave Study V2 was run on the immutable 500-symbol V3 temporal fact and its authoritative lifecycle/entry/exit ledger. No chip shard, ledger, strategy threshold, or strategy semantic was rebuilt or changed.

The result is **mixed**, not a strategy-redesign mandate:

- Price labels are independent of chip/strategy state and begin on T+1. Of 121,251 frozen feature rows, 121,186 had a complete valid 60-session price-outcome window. There were 30,448 dense raw upside-positive rows, reduced deterministically to 1,599 independent wave events.
- All 1,599 waves have an exact authoritative production decision on T immediately before event start. All 1,599 are authoritatively proven non-entries. Production classified every selected wave as **no setup**; the exact first failure was `hard_valid` for 1,225, `setup_score` for 373, and `tradable` for one.
- Canonical V3 base existence, age, mass, and prominence do not provide broad, stable launch separation. Age and prominence have some low-coverage, directionally mixed evidence; mass does not.
- V3 temporal data does add limited information. Twenty-session ensemble-ambiguity persistence is weak but consistent, and recent peak-location/band changes separate later winners among the minority of rows with a live canonical base. Lifecycle event density is regime-dependent.
- The strongest repeatable T−1 separation comes from five-session changes in price-relative cost anchors and profit ratio. Lead analysis shows that much of this effect fades or reverses at T−5/T−10/T−20. It is best treated as contemporaneous pre-launch price/chip confirmation, not a durable early predictor.
- The accepted thresholds cannot be responsibly loosened or tightened from this evidence. The setup threshold rejected both winners and controls with no conditional separation, while breakout/retest/retention gates were not reached on sampled event dates. The authoritative execution ledger contains no false-positive trades against which to price a recall gain.

The prior V1 conclusion therefore mostly survives: simple scalar chip state is weak as an early, standalone launch predictor. Canonical V3 adds some temporal observability, especially ambiguity persistence, but not enough stable, broad-coverage information to justify strategy redesign.

## Scope and governed inputs

The implementation baseline is `f502367049ad291dc703c63fdd594798171c9e97`. All new files are under `research/v12-reverse-wave-v2`.

| Governed item | Verified identity |
|---|---|
| Frozen V3 root manifest | `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a` |
| Authoritative freeze lock | `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9` |
| V3 daily-feature parts | 500/500 size- and SHA-256-verified; 25,623,241 bytes |
| Feature rows / symbols | 121,251 / 500 |
| Canonical strict temporal-valid rows | 36,219 |
| Ledger manifest | `4b4ba0325f41dfcda5f9a7e8e3f259907dbf596f5b2863f622bf2503c7e30254` |
| Accepted production parameter | `9baed76ec299161c` |
| Registered daily-price inventory | `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2` |

The root manifest, lock, every consumed feature shard, all four ledger Parquets, and the registered CY-006 2020/2021 partitions were directly rehashed before analysis. The root and lock were rechecked after the run.

The frozen feature fact does not contain OHLC. Price-only outcomes therefore use the exact registered CY-006 dependency already bound by the authoritative replay, not an unregistered substitute. The 2021 partition is used only to complete forward outcome windows for late-2020 feature observations; it contributes no feature, setup, gate, or strategy state.

## Price-only outcome contract

### T+1 start and economic coordinate

For a frozen V3 observation available at the close of bar T:

1. Event start is the next recorded trading session T+1.
2. The baseline is T close in an economic price index formed by chaining `close / preclose`.
3. Future highs and lows are mapped into the same coordinate with `high / preclose` and `low / preclose` before applying the daily chain.
4. This removes mechanical ex-date coordinate resets without reading chip state, strategy state, or future research features.
5. A label is emitted only when the baseline and all 60 future price bars pass the price-field validity/positivity checks.

The upside labels are:

- `up20_20`: future mapped high reaches +20% within 20 sessions;
- `up30_40`: future mapped high reaches +30% within 40 sessions;
- `up50_60`: future mapped high reaches +50% within 60 sessions.

Controls retained alongside them are:

- `down10_20`: future mapped low reaches −10% within 20 sessions;
- `down20_60`: future mapped low reaches −20% within 60 sessions;
- `neutral_60`: maximum return is below +10% and minimum return remains above −10% over 60 sessions.

The machine-readable price label table contains only price identity, event timing, economic price outcomes, and source snapshots. Chip features are joined only after event segmentation.

### Deterministic wave de-duplication

Dense observations are not treated as independent discoveries.

For each symbol, the union of all three upside-positive candidate rows is divided into chronological runs. Two positive candidates remain in the same run when no more than five nonpositive candidates intervene. One event is retained per run: the candidate with the lowest economic baseline close, with the earliest date breaking a tie. This rule is fixed, price-only, and applied before feature analysis.

Controls are upside-negative starts selected only after 20 sessions of feature history, at least 60 sessions apart, and more than 60 sessions from a selected wave start. The resulting control set is deliberately sparse. Precision and lift below refer to this event sample, not to the raw market-row prevalence.

## Chronological protocol and samples

No observation was randomly assigned across time.

| Split | Feature dates | Raw rows | Raw union-positive rate (95% Wilson CI) | De-duplicated waves | Spaced controls |
|---|---|---:|---:|---:|---:|
| Discovery | through 2020-04-30 | 39,421 | 22.10% (21.70%, 22.51%) | 643 | 139 |
| Validation | 2020-05-01 through 2020-08-31 | 40,918 | 35.71% (35.24%, 36.17%) | 541 | 169 |
| Holdout | from 2020-09-01 | 40,847 | 17.44% (17.08%, 17.81%) | 415 | 342 |
| Total | — | 121,186 | 25.13% | 1,599 | 650 |

De-duplicated wave-label counts were 1,223 for +20%/20, 893 for +30%/40, and 434 for +50%/60. Labels overlap by construction. Among the 650 spaced controls, 152 reached −10%/20, 168 reached −20%/60, and 106 were neutral over 60 sessions.

Uncertainty for univariate feature AUC uses 200 deterministic symbol-cluster bootstrap resamples within each chronological split. Wave segmentation plus symbol-level resampling prevents dense rows from a single rally or a repeatedly observed symbol from receiving row-level independent weight.

## Feature construction

The study separates four kinds of inputs:

- **absolute state:** base existence, canonical age/mass/prominence/band/location, concentration, profit ratio, cost anchors, and model spreads;
- **recent change:** T minus T−5/T−10/T−20 changes, with peak-specific changes null unless the same canonical `peak_track_id` exists at both endpoints;
- **persistence:** base-presence fractions, same-binding run age, ambiguity rate, and lifecycle-event counts;
- **lifecycle/event state:** split, merge, loss, rebinding, and ensemble ambiguity.

`peak_track_mass`, `peak_track_prominence`, `peak_track_age`, and the tracked band/location always come from canonical V3 fields. No dominant-band or V1 scalar is substituted when a canonical base is absent.

`rolling_base_episode_age` and `days_since_rebinding` are derived only from frozen target-year binding observations. An episode already active on the first frozen target date is left-censored; `days_since_rebinding` remains null until an in-window rebind is actually observed. Canonical `peak_track_age` remains the authority for economic peak age.

## Main feature results

The table reports AUC with “winner higher” orientation. Values below 0.5 mean lower values precede winners. Coverage is the holdout winner availability unless the feature is always defined.

| Feature | Discovery AUC | Validation AUC | Holdout AUC (cluster 95% CI) | Holdout winner coverage | Interpretation |
|---|---:|---:|---:|---:|---|
| Base exists | 0.473 | 0.485 | 0.463 (0.429, 0.499) | 100% indicator | Weak negative association; not a positive screen |
| Strict temporal valid | 0.467 | 0.497 | 0.451 (0.418, 0.487) | 100% indicator | Winners were slightly less likely to be strict-valid |
| Canonical peak age | 0.422 | 0.441 | 0.436 (0.365, 0.506) | 32.3% | Younger tendency, low coverage and uncertain |
| Canonical peak mass | 0.436 | 0.535 | 0.447 (0.366, 0.520) | 32.3% | Direction changes; weak |
| Canonical prominence | 0.436 | 0.526 | 0.421 (0.352, 0.479) | 32.3% | Lower in holdout, but validation reverses |
| Base presence, 20 sessions | 0.466 | 0.461 | 0.428 (0.385, 0.470) | 100% in holdout | Less base persistence before holdout winners; discovery weak |
| Ambiguity rate, 20 sessions | 0.544 | 0.545 | 0.569 (0.527, 0.611) | 100% | Modest, consistent V3 temporal information |
| Merge-event count, 20 sessions | 0.722 | 0.452 | 0.624 (0.586, 0.662) | 100% in validation/holdout | Regime-dependent, not stable enough alone |
| Peak-location relative-price change, T−5 | 0.587 | 0.849 | 0.764 (0.693, 0.831) | 21.2% | Strong local confirmation, very low canonical-base coverage |
| Average-cost relative-price change, T−5 | 0.683 | 0.811 | 0.772 (0.736, 0.809) | 100% | Strong near-launch price/cost confirmation |
| Profit-ratio change, T−5 | 0.216 | 0.239 | 0.307 (0.275, 0.344) | 100% | Profit ratio falls sharply near selected launch troughs |

### Timing classification

Lead analysis prevents a T−1 association from being called an early predictor automatically.

- In holdout, average-cost relative-price AUC was 0.588 at T−1, 0.491 at T−5, 0.467 at T−10, and 0.445 at T−20. The strong recent-change feature is therefore the move into the T−1 dislocation, not a stable high level weeks earlier.
- Holdout profit-ratio AUC changed from 0.430 at T−1 to 0.530/0.571/0.585 at T−5/T−10/T−20. The direction reverses as the launch trough approaches.
- Peak-location recent change is strong only where a canonical base is observable. Raw peak location is weak in discovery/holdout and coverage is about one third before considering same-ID change requirements.
- Ensemble ambiguity is the exception: ambiguity direction remains positive at T−1/T−5/T−10/T−20 across all three splits, although the magnitude is modest.

Accordingly, price-relative cost, profit, and peak-location changes are classified as **primarily contemporaneous confirmation**. Ambiguity persistence is a **meaningful but weak pre-launch predictor**. Base age/mass/prominence and persistence remain weak or mixed.

## Discovery-fitted continuous thresholds

For every continuous feature and each of the four targets (`any_upside` plus the three explicit outcome labels), discovery-only directional thresholds were computed to cover approximately 80%, 90%, and 95% of discovery winners. Those thresholds were applied unchanged to validation and holdout. The complete table has 2,214 rows.

Representative 90%-coverage discovery thresholds for the union target are:

| Feature / discovery rule | Holdout recall, missing as fail | Holdout recall among available | Holdout control pass rate | Holdout event-sample lift |
|---|---:|---:|---:|---:|
| Peak age ≤ 191 | 30.6% | 94.8% | 36.5% | 0.92 |
| Peak mass ≤ 0.5548 | 28.9% | 89.6% | 31.6% | 0.96 |
| Peak prominence ≤ 0.02158 | 27.5% | 85.1% | 32.5% | 0.92 |
| Base presence 20 ≤ 0.85 | 90.6% | 90.6% | 79.5% | 1.06 |
| Ambiguity rate 20 ≥ 0.10 | 91.3% | 91.3% | 81.6% | 1.05 |
| Peak-location relative change T−5 ≥ 0.02247 | 17.6% | 83.0% | 15.2% | 1.07 |
| Average-cost relative change T−5 ≥ 0.03086 | 75.4% | 75.4% | 36.0% | 1.31 |
| Profit-ratio change T−5 ≤ −0.02842 | 80.2% | 80.2% | 52.9% | 1.18 |

This table makes the coverage/false-positive tradeoff explicit. Age, mass, and prominence can cover most *available* discovery winners only because missing bases remove roughly two thirds of all winners; their overall recall and lift are poor. Ambiguity/base-presence thresholds have high recall but admit about 80% of controls. The near-launch cost-change threshold is more selective, but it measures a contemporaneous dislocation and is not an audited production gate.

## V2 versus the V1 conclusion

The prior V1 conclusion was that simple scalar chip features had weak pre-launch predictive power.

V2 changes that conclusion only partially:

| Family | Classification | V2 conclusion |
|---|---|---|
| Structural-base existence | Weak predictor | Existence/strict validity is not positively selective |
| Peak age | Weak predictor | Winners tend younger when available, but coverage and uncertainty are limiting |
| Peak mass | Weak predictor | No stable split-consistent separation |
| Peak prominence | Weak predictor | Holdout difference does not survive with a stable validation direction |
| Peak shape/location | Primarily contemporaneous confirmation | Recent change can be strong, but only on low-coverage live-base rows |
| Base persistence | Weak predictor | Lower recent presence appears in validation/holdout; episode-age direction is unstable |
| Lifecycle event density | Weak predictor | Discovery/holdout effects do not survive validation consistently |
| Ensemble ambiguity | Meaningful pre-launch predictor | Persistence adds modest, repeatable information at multiple leads |
| Scalar chip state | Primarily contemporaneous confirmation | Strong near-trough movement, weak/inconsistent longer-lead state |
| Cost anchors | Primarily contemporaneous confirmation | Strong T−1 change separation, but lead decay and price-relative mechanics dominate |
| Model consensus | Weak predictor | Some holdout separation, insufficient stable evidence |

Thus `TEMPORAL_V3_ADDS_PRELAUNCH_INFORMATION` is **MIXED**. V3 supplies better lifecycle observability and a usable ambiguity hypothesis, but it does not turn canonical mass/prominence/age/base persistence into reliable broad-coverage predictors.

## Authoritative production attribution

Attribution uses the exact production decision at feature date T, which is strictly before T+1 event start. For each wave the study joins:

- lifecycle event/state;
- all blocking failed gates in production order;
- exact observed JSON value, operator, exact threshold JSON, reason code, and source function;
- execution history strictly before event start.

All 1,599 waves have exact same-decision lifecycle and gate coverage. The governed execution table is a valid zero-row artifact, so there are no entry intents, attempts, fills, open positions, or exits to infer or fabricate.

| Production category before wave | Events |
|---|---:|
| No setup | 1,599 |
| Setup observed | 0 |
| Breakout not qualified | 0 |
| Breakout qualified but retest/gates failed | 0 |
| Qualified | 0 |
| Entry intent created | 0 |
| Execution attempted but not filled | 0 |
| Actually entered before wave | 0 |
| Already holding before event | 0 |
| Unavailable/other | 0 |

Exact first failed gates:

| First failed gate | Waves |
|---|---:|
| `hard_valid` | 1,225 |
| `setup_score` | 373 |
| `tradable` | 1 |

All-failure combinations were `hard_valid + peak_identity_valid` for 1,085 waves, `hard_valid` alone for 140, `setup_score` alone for 373, and `tradable` alone for one.

This is why every selected event may be called a production missed winner: absence of entry is proven by the authoritative ledger, not inferred from a missing trade file or reconstructed strategy approximation.

## Existing production-threshold audit

The audited accepted thresholds remain unchanged:

| Gate | Threshold | Event-sample winner evidence | Event-sample control evidence | Conclusion |
|---|---:|---:|---:|---|
| Accumulation score | ≥ 1.00 | 373 evaluated; all 373 failed; observed value 0.0 | 191 evaluated; all failed; values 0.0 to 0.2 | No conditional information; failure volume alone cannot justify loosening |
| Breakout excess | ≥ 0.25 ATR | Not reached on selected event dates | Not reached on selected control dates | Global ledger has only nine failed evaluations; no event-sample tradeoff |
| Retest depth | ≤ 0.50 ATR | Not reached | Not reached | Not estimable from authoritative real-data exposure |
| Cost migration | ≥ 0.50 ATR | Not reached | Not reached | Not estimable |
| Volume ratio | ≤ 0.80 | Not reached | Not reached | Not estimable |
| Turnover ratio | ≤ 0.80 | Not reached | Not reached | Not estimable |
| Root-anchor retention | ≥ 70% | Not reached | Not reached | Not estimable |

The setup-score gate had a conditional winner pass rate of 0% and a conditional control pass rate of 0%; marginal information conditional on prior gates is zero in this sample. Downstream marginal information is unavailable because production never exposed those gates on selected event/control dates.

This audit is complete as an audit of authoritative evidence: each requested gate is represented with its exact threshold and its reached/not-reached status. It is not statistical evidence that unreached thresholds are correct. It is evidence that their counterfactual false-positive tradeoff cannot be learned from this ledger.

No threshold change is justified. In particular, “many winners failed” is not sufficient: the setup gate also rejected all reached controls, and the execution ledger provides no qualified/entered false positives for comparison.

## Limitations

- This is one frozen target year and one 500-symbol universe. Chronological splits expose strong regime variation; they are not independent market cycles.
- The 650 controls are deliberately sparse, non-overlapping research controls. Event-sample precision/lift is not market-wide precision; raw row base rates are reported separately.
- Canonical base-dependent fields cover only about 31–40% of event rows. Missingness is not imputed, and V1 scalars are not substituted.
- Full warmup-history rebinding timestamps are not recoverable from the target-only frozen fact. In-window rebinding is exact; left-censored episodes are explicit.
- The authoritative production ledger has one setup globally and no qualification/entry. It supports exact missed-winner attribution but cannot identify downstream threshold tradeoffs.
- The study audits associations and fixed discovery coverage thresholds. It does not fit, optimize, or recommend a new strategy.

## Machine-readable deliverables

All result artifacts are under `results/`:

- `price_wave_labels.parquet`: price-only T+1 labels for all eligible frozen rows;
- `wave_events.parquet`, `control_events.parquet`, `event_sample.parquet`: de-duplicated analysis samples and joined pre-event features;
- `production_attribution.parquet`: one authoritative production category per wave;
- `rejected_winner_gates.parquet`: exact long-form failed-gate operands/thresholds;
- `feature_catalog.csv`: family/category/definition of every analyzed feature;
- `feature_univariate.csv`: split/target counts, coverage, medians, AUC, and cluster intervals;
- `feature_threshold_coverage.csv`: discovery-fit 80%/90%/95% thresholds tested unchanged;
- `feature_lead_analysis.csv`: T−1/T−5/T−10/T−20 timing results;
- `threshold_audit.csv`: production gate distributions, pass rates, rejections, and conditional evidence;
- `feature_family_classification.csv`: machine-readable final family classifications;
- `sample_summary.csv`, `production_attribution_counts.csv`, and `verdicts.json`;
- `manifest.json`: input identities, study contract, row counts, and output hashes.

The reproducible runner is `run_reverse_wave_v2.py`; focused nullable-field and exact rejection-count regressions are in `test_reverse_wave_v2.py`.

## Required verdicts

`PRICE_WAVE_LABELS_PIT_SAFE: YES`

`PRODUCTION_ENTRY_ATTRIBUTION_AUTHORITATIVE: YES`

`MISSED_WINNER_ATTRIBUTION_AUTHORITATIVE: YES`

`TEMPORAL_V3_ADDS_PRELAUNCH_INFORMATION: MIXED`

`ROLLING_BASE_PERSISTENCE_HAS_SIGNAL: MIXED`

`PEAK_AGE_HAS_SIGNAL: MIXED`

`PEAK_MASS_HAS_SIGNAL: NO`

`PEAK_PROMINENCE_HAS_SIGNAL: MIXED`

`ENSEMBLE_AMBIGUITY_HAS_INFORMATION: YES`

`EXISTING_THRESHOLD_AUDIT_COMPLETE: YES`

`STRATEGY_THRESHOLD_CHANGE_JUSTIFIED: NO`

`SAFE_TO_PROCEED_TO_STRATEGY_REDESIGN: NO`
