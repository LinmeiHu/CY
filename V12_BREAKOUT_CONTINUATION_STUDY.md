# V12 Breakout Continuation / Failure Study

Date: 2026-08-28

Branch: `research/v12-continuation-study`

Baseline: `f502367049ad291dc703c63fdd594798171c9e97`

## 1. Executive conclusion

The requested conditional continuation question is **not statistically identifiable in
the governed frozen sample**.

The authoritative 500-symbol lifecycle ledger contains one setup, zero authoritative
breakout observations, zero retests, zero qualifications, and zero entries. The nine
rows named `BREAKOUT_REJECTED` are nine daily evaluations of the same still-accumulating
lifecycle; they are not nine breakout events. Every one fails the unchanged production
`breakout_excess_atr >= 0.25` gate. Consequently, the primary breakout-conditioned
cohort has zero rows in discovery, validation, and holdout.

No successful-continuation, failed-breakout, or ambiguous-breakout groups can be formed.
Continuation base rates, lift, precision, recall, coverage, confidence intervals for
outcomes, feature effects, and pass-versus-fail gate discrimination are therefore
undefined. Treating setup rejections, raw price crosses, dominant-peak changes, or the
27,317 accumulation evaluations as breakout events would replace the authoritative
production event with a research proxy and violate the study objective.

This report does three things that remain valid with a zero-event cohort:

1. proves the cohort count directly from the immutable ledger and binds the exact input
   identities;
2. defines a deterministic, T+1 and PIT-safe continuation/failure label protocol for an
   authoritative breakout cohort;
3. audits the production breakout/retest gate funnel without changing any threshold.

The one authoritative setup is shown separately as a non-inferential sensitivity case.
It is not promoted into the primary breakout cohort.

In the final flags, `NO` for a predictor or gate means **not demonstrated / not
estimable from this frozen cohort**. It does not establish that the true effect is zero.
`MIXED` is reserved for conflicting estimable evidence and is therefore not appropriate
for an empty cohort.

## 2. Governed inputs and immutability

No chip artifact, lifecycle artifact, parameter, or production threshold was rebuilt or
modified. No full-market job was started.

### 2.1 Frozen V3 temporal data

| Item | Bound value |
|---|---|
| Root | `/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828` |
| Bundle | `v12-v3-500-temporal-2020` |
| Target year | 2020 |
| Symbols | 500 |
| Daily feature rows | 121,251 |
| Date range | 2020-01-02 through 2020-12-31 |
| Root manifest SHA-256, directly rechecked | `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a` |
| Governed freeze-lock SHA-256 | `95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9` |
| Frozen tree SHA-256 recorded by the ledger replay | `e33fb84ecabfd33f8bb357569a1d57086ac2acf4d201c00e4e2b5d61aa085d91` |
| Peak track | `temporal-chip-peak-v3` |
| Peak definition | `canonical-chip-peak-v2` |
| Seller models | `UNIFORM`, `DISPOSITION`, `ACTIVE_STICKY` |

The daily candidate scan found 500 symbols and exactly 121,251 rows. It found zero
feature rows whose `available_at` was later than the 15:30 evaluation time. This check
does not relax validity: strict shard `hard_valid` is zero, while the governed ledger
adapter separately preserves research validity and forces invalid observations closed.

### 2.2 Authoritative lifecycle ledger

| Item | Bound value |
|---|---|
| Root | `/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_exit_ledger_500_20260828` |
| Artifact kind | `POST_HOC_REPLAY_ARTIFACT` |
| Status | `COMPLETE` |
| Ledger schema | `v12-lifecycle-entry-exit-ledger-v1` |
| Accepted parameter ID | `9baed76ec299161c` |
| Strategy | `markup-retest-v3-tracked-peak` |
| V3 build commit | `c81bc30a381e8cebcc5b9f8d36524a8a4c9f0151` |
| Ledger implementation commit | `3488a95dfb17815e7ea23f065c702106dcd10437` |

Direct artifact hashes matched the ledger manifest:

| Artifact | Rows | SHA-256 |
|---|---:|---|
| `lifecycle_events.parquet` | 121,252 | `66a120d028a268696df8a5b85702a4ca0d7db95da8639134de8310da35ac65e7` |
| `decision_gates.parquet` | 555,418 | `35817766cf05f6b7a5e77078735f6226698fd51955204926ae852f6a1f111381` |
| `execution_events.parquet` | 0 | `7cb6111adb970b9b4cff51f511e0fadc46ca4698ef996f6068dea1b4d99f432b` |
| `lifecycle_summary.parquet` | 1 | `7d1d9876a0cc98140380f9fc497449bea27a792a428be1f240a5ed29bdce6b3e` |

Direct audits found zero `available_at > decision_at` violations in all 121,252
lifecycle rows and all 555,418 decision-gate rows. The execution table is empty.

The registered CY-006 daily-bar inventory bound by the ledger manifest was used only
for the quarantined setup outcome diagnostic. No unregistered price source was
substituted.

## 3. Authoritative event definition

### 3.1 Primary breakout event

The primary event is one unique lifecycle transition emitted by the existing production
machine as `BREAKOUT_OBSERVED`:

- the lifecycle is already in `ACCUMULATING`;
- its immutable accumulation root exists;
- the observation is valid and tradable under the production ordering;
- accumulation has not expired; and
- `breakout_excess_atr >= 0.25` under accepted parameter
  `9baed76ec299161c`.

The transition freezes, at that decision time, support, ATR, volume, turnover,
pre-breakout average cost, and pre-breakout cost p50. Event identity is
`(lifecycle_id, breakout_time)`, not a daily gate row. Multiple rejected daily
evaluations of one lifecycle are not independent events.

This definition is authoritative because the ledger observes
`LifecycleMachine.advance`; it does not reconstruct a second breakout rule.

### 3.2 Setup-only sensitivity event

`SETUP_OBSERVED` plus `ROOT_ANCHOR_BOUND` is an authoritative setup milestone but is not
a breakout. It may be used only in a separately labelled sensitivity section. It cannot
support frozen-breakout-support, retest, cost-migration-in-ATR, or production
breakout-failure outcomes because those causal anchors do not exist until a breakout
transition.

### 3.3 Rejected proxy definitions

The following were deliberately not used as primary events:

- `BREAKOUT_REJECTED` rows;
- raw close above a rolling peak or band;
- a rolling-base rebind, split, merge, or loss;
- setup-score component rows that did not create a setup;
- relaxed parameter-grid events; or
- ex-post price paths selected for looking breakout-like.

Using any of these would either change production semantics or turn the study back into
a general pre-launch predictor study.

## 4. Prospective continuation/failure label contract

The following contract is deterministic and can be applied without change when an
authoritative breakout cohort exists. It produced an empty primary label table here.

### 4.1 Evaluation landmarks and feature clock

For each authoritative breakout `B`:

- `B0`: the breakout decision at 15:30;
- `R`: each production retest evaluation from breakout trading day +1 through +10;
- `B+1`, `B+3`, and `B+5`: optional post-breakout landmark evaluations.

At a landmark `e`, a feature is eligible only when its source has
`available_at <= decision_at(e)`. A delta such as breakout-to-retest cost migration may
use only the frozen `B0` value and the value known at `e`. Unknown snapshot identity,
lineage, corporate-action coordinate, or required frozen anchor makes the feature row
invalid; it is never imputed from a daily proxy.

Each landmark predicts forward from itself. For example, `B+5` features predict the
next 5/10/20/40 trading days from `B+5`; they are not evaluated against a five-day label
that ended at `B+5`.

### 4.2 Horizon and T+1 rule

For horizon `h` in `{5, 10, 20, 40}`, outcome bars are the next `h` legal trading
observations after the landmark. The landmark bar itself is excluded. Suspensions do
not create synthetic bars, and a signal on bar `t` cannot fill in bar `t`.

Corporate actions must use the authoritative lifecycle/economic coordinate rebase. A
missing or blocking action censors the affected label instead of silently using an
unadjusted comparison. A label is available only at the end of its horizon; chronological
model selection must use `label_available_at`, not merely event date.

### 4.3 Continuous and binary outcomes

Let `P_e` be the landmark close in the valid economic coordinate, and let bars
`u = 1..h` follow the landmark.

| Outcome | Deterministic definition |
|---|---|
| Positive continuation | `close(e+h) / P_e - 1 > 0` |
| Close return | `R_h = close(e+h) / P_e - 1` |
| Maximum favorable excursion | `MFE_h = max(high(e+u) / P_e - 1)` |
| Maximum adverse excursion | `MAE_h = min(low(e+u) / P_e - 1)` |
| Failure below frozen support | any rebased `close(e+u) < frozen_breakout_support` |
| Price-structure failure | the production predicate `close < frozen support - 1.5 * current ATR` |
| Material percentage drawdown | `MAE_h <= -10%`; this is a study label, not a production threshold |
| Material ATR drawdown | any `low(e+u) <= P_e - 1.5 * frozen_breakout_ATR`; this is reported beside, not substituted for, the percentage label |
| Authoritative hypothesis failure | the first production lifecycle failure/exit condition recorded after the landmark: root/price structure broken, protective stop, confirmed distribution, data/corporate-action invalidation, or other canonical reason |
| Stop failure | the canonical protective-stop condition and its later legal fill are recorded separately; an intent is not a fill |

An incomplete horizon is right-censored, not labelled a failure or non-continuation.

### 4.4 Successful, failed, and ambiguous/noisy classes

The primary comparison horizon is 20 trading days, with the same classification also
reported at 5, 10, and 40 days:

- **failed breakout**: support failure, material drawdown, or authoritative hypothesis
  failure occurs within the horizon;
- **successful continuation**: close return is positive and no failure condition occurs;
- **ambiguous/noisy**: the horizon is complete, no failure condition occurs, but the
  close return is non-positive or the secondary horizon signs conflict;
- **censored**: the required horizon or lineage/action coordinate is incomplete; this is
  not part of any of the three outcome classes.

## 5. Chronological protocol and uncertainty

The pre-specified temporal partitions for this 2020-only feature bundle are:

| Partition | Breakout date |
|---|---|
| Discovery | 2020-01-02 through 2020-06-30 |
| Validation | 2020-07-01 through 2020-09-30 |
| Holdout | 2020-10-01 through 2020-12-31 |

For each horizon, trailing events whose `label_available_at` crosses the next partition
boundary must be purged, followed by the existing five-trading-day embargo. Feature
cutoffs and candidate rules may be selected only in discovery, checked once in
validation, and frozen before holdout. Results must be clustered by lifecycle/symbol so
daily landmarks from one breakout do not become independent observations.

For an estimable cohort, the report would use:

- base rate: positives divided by complete eligible event labels;
- lift: selected positive rate divided by the same split's base rate;
- precision: true successful continuations divided by selected events;
- recall: selected successful continuations divided by all successful continuations;
- coverage: selected events divided by all complete eligible events;
- uncertainty: exact or Wilson binomial intervals for unclustered descriptive rates and
  lifecycle/symbol-cluster bootstrap intervals for feature/gate comparisons.

No rule would be declared predictive from discovery alone. No such selection or model
fit was attempted because all three primary partitions contain zero breakout events.

## 6. Observed cohort and base rates

### 6.1 Authoritative funnel

| Stage | Count | Notes |
|---|---:|---|
| Symbols | 500 | Frozen universe |
| Evaluation rows | 121,251 | 2020 only |
| Rows passing the ledger `hard_valid` gate | 27,736 | 22.8749% of evaluation rows |
| Tradability failures after validity phase | 410 | Canonical lifecycle ordering retained |
| Setup-score evaluations | 27,317 | Five component rows also recorded |
| Setup-score passes / setups | 1 / 1 | 0.0036607% of setup evaluations |
| Unique lifecycle summaries | 1 | `000709.SZ` |
| Breakout daily evaluations | 9 | One lifecycle, serially dependent |
| Authoritative breakouts | 0 | Primary cohort |
| Retest gate evaluations | 0 | No lifecycle reached `BREAKOUT` |
| Retests / qualifications | 0 / 0 | — |
| Entry intents / fills | 0 / 0 | — |
| Exit conditions / fills | 0 / 0 | — |

The raw exact-binomial 95% interval for one setup-score pass in 27,317 daily evaluations
is approximately 0.0000927% to 0.0203945%. This interval is descriptive only because
rows are serially and cross-sectionally dependent.

The breakout qualification rate is 0/1 lifecycle. Its two-sided exact-binomial 95%
interval is 0% to 97.5%, which illustrates that the sample supplies essentially no
information about the lifecycle-level rate. Treating the nine repeated days as trials
would give 0/9 and an upper bound of about 33.63%, but that calculation is not a valid
event-level uncertainty estimate.

### 6.2 Outcome metrics

| Metric | Discovery | Validation | Holdout | Overall |
|---|---:|---:|---:|---:|
| Authoritative breakout events | 0 | 0 | 0 | 0 |
| Complete 5-day labels | 0 | 0 | 0 | 0 |
| Complete 10-day labels | 0 | 0 | 0 | 0 |
| Complete 20-day labels | 0 | 0 | 0 | 0 |
| Complete 40-day labels | 0 | 0 | 0 | 0 |
| Successful continuation | N/A | N/A | N/A | N/A |
| Failed breakout | N/A | N/A | N/A | N/A |
| Ambiguous/noisy breakout | N/A | N/A | N/A | N/A |
| Base rate | N/A | N/A | N/A | N/A |
| Lift | N/A | N/A | N/A | N/A |
| Precision | N/A | N/A | N/A | N/A |
| Recall | N/A | N/A | N/A | N/A |
| Coverage | N/A | N/A | N/A | N/A |
| Outcome uncertainty | unidentified | unidentified | unidentified | unidentified |

`N/A` is used rather than zero: zero would falsely claim an observed continuation or
failure rate in a cohort with no denominator.

## 7. Requested feature audit

The frozen V3 shards contain rolling-base identity/age, mass, prominence, concentration,
profit ratio, seller-model spread, and split/merge/lost/ambiguity state. Across the full
shard there are 41,619 `TRACKED` rows. There are also 20,210 loss flags, 10,501 split
flags, 14,504 merge flags, and 1,798 observed rebindings across 451 symbols. These are
feature-availability facts, not breakout-conditioned samples.

| Requested hypothesis | Authoritative PIT-safe operand | Breakout-conditioned result |
|---|---|---|
| Rolling-base persistence / base age | rolling base ID and `peak_track_age` at landmark | Not estimable; 0 events |
| Days since rebinding | current base episode derived from immutable base ID; no identity bridging across loss | Not estimable; 0 events |
| Peak mass / prominence | tracked-base mass and prominence, no dominant-peak fallback | Not estimable; 0 events |
| Concentration | contemporaneous V3 concentration fields | Not estimable; 0 events |
| Root-anchor retention | `exact_anchor_retention` lower/central/upper and model values against immutable setup root | Not evaluated after breakout |
| Cost migration | minimum of average-cost and p50 migration divided by frozen breakout ATR | Undefined without a breakout |
| Profit ratio | contemporaneous V3 profit ratio | Not estimable; 0 events |
| Seller agreement / ambiguity | exact disagreement in ATR plus V3 ambiguity/spread fields | Not estimable; 0 events |
| Split / merge / lost | V3 transition flags and exact root-lineage result | Not estimable; 0 events |
| Volume / turnover compression | retest values divided by frozen breakout volume/turnover | Undefined without a breakout |
| Retest quality | exact depth, support regain, absorption, market/sector, retention, compression gates | No retest evaluations |
| Breakout-to-retest/post-breakout changes | landmark value minus frozen `B0` value, using only state known at landmark | No valid landmark pairs |

The requested test of whether weak pre-launch predictors become useful conditional
predictors after breakout cannot be performed. There is no conditional cohort on which
to estimate a change in usefulness, and the setup-only case below cannot supply a
cross-sectional or chronological comparison.

## 8. Setup-only sensitivity case (not primary evidence)

The sole setup is `000709.SZ` on 2020-12-18:

| Field | Value |
|---|---|
| Lifecycle ID | `b3267301729d1997a75a8a5d518bbf720af2c8571478f2235fc35033d360c975` |
| Immutable root ID | `d0569e263287021f871104122a7dab4233f5b5063100314756f72906cd26d51c` |
| State at year end | `ACCUMULATING` |
| Frozen breakout support / ATR / volume / turnover | null / null / null / null |
| Breakout excess on nine later evaluations | -22.1927 to -17.8153 ATR |
| Seller-model disagreement on those evaluations | 3.1322 to 3.4098 ATR; all above 3.0 |

The V3 feature row known at the setup decision had base age 408, tracked mass 0.068753,
prominence 0.003931, concentration 0.567614, profit ratio 0.483077, five peaks, and no
split/merge/lost/ambiguity flag. These values are a single observation and cannot
estimate a feature effect.

For context only, the registered CY-006 daily bars after the setup give this path from
the 2.30 setup close. The setup bar is excluded, all horizons start T+1, all used bars
are valid/tradable, and no corporate action occurs in the 40-day window.

| Horizon | End date | Close return | MFE | MAE | 10% material drawdown |
|---:|---|---:|---:|---:|---|
| 5 | 2020-12-25 | +1.7391% | +2.6087% | -2.6087% | No |
| 10 | 2021-01-04 | -2.6087% | +2.6087% | -3.4783% | No |
| 20 | 2021-01-18 | -5.6522% | +2.6087% | -6.5217% | No |
| 40 | 2021-02-22 | -2.1739% | +2.6087% | -11.7391% | Yes |

The first 10% adverse excursion occurs on trading day 29, 2021-01-29. This is a noisy,
initially positive then adverse **setup** path, not a failed breakout label. Frozen
support failure, retest quality, authoritative root retention, and cost migration remain
undefined because no breakout anchors were frozen.

## 9. Production breakout/retest gate audit

The accepted production values were left unchanged: setup score 1.00, breakout excess
0.25 ATR, retest depth 0.50 ATR, cost migration 0.50 ATR, retest volume and turnover
ratios 0.80, root-retention lower bound 0.70, and seller disagreement at most 3.00 ATR.

### 9.1 Observed gate behavior

| Gate | Evaluations | Pass | Fail | First blocking failure |
|---|---:|---:|---:|---:|
| `setup_score >= 1.00` | 27,317 | 1 | 27,316 | 27,316 |
| accumulation not expired | 9 | 9 | 0 | 0 |
| `breakout_excess_atr >= 0.25` | 9 | 0 | 9 | 9 |
| seller disagreement `<= 3.00` at breakout phase | 9 | 0 | 9 | 0; non-blocking in this phase |
| every retest gate | 0 | 0 | 0 | 0 |

The nine breakout-excess observations range from -22.1927 to -17.8153 ATR. They are not
near-threshold cases. The unchanged breakout gate reduces the observed funnel from one
setup to zero breakouts. The retest gates never receive an observation and therefore
have no measurable count or outcome effect in this artifact.

### 9.2 Discrimination versus opportunity reduction

Discrimination requires outcome-bearing pass and fail groups. This ledger has no
breakout pass group and no retest evaluation group. Precision, recall, lift, and
coverage for the current breakout/retest gates cannot be calculated. The only observed
effect is opportunity reduction to zero after the sole setup.

It is not valid to claim that the breakout gate prevented a future failure from this one
setup path, because the setup never met the authoritative event definition and there is
no matched passing group. It is also not valid to claim the retest gates are useful or
harmful: they were never invoked.

Accordingly, the evidence does not establish discriminative value for the current
retest gates. This conclusion does not authorize relaxing them.

## 10. What can and cannot be concluded

Supported conclusions:

- the production breakout definition and its ledger provenance are authoritative;
- the proposed continuation/failure label clock is PIT-safe and T+1-safe;
- the frozen authoritative breakout cohort is empty;
- the sole setup remains accumulating and supplies no breakout/retest anchors;
- current breakout gating reduces this sample to zero opportunities; and
- current retest-gate discrimination is untestable because there are zero evaluations.

Unsupported conclusions:

- that temporal V3 does or does not predict continuation in the population;
- that root retention, cost migration, peak persistence, or seller agreement has a
  positive, negative, or mixed conditional effect;
- that weak pre-launch features become strong after breakout;
- that any current production threshold should be changed; or
- that the setup-only case represents a failed breakout.

An estimable follow-up would require multiple authoritative `BREAKOUT_OBSERVED` events,
complete forward bars, exact frozen breakout memory, and lineage-resolved landmark
features across genuinely chronological periods. That input does not exist in this
frozen 2020 ledger. Creating it would require a separately authorized governed build;
none was started here.

## 11. Redesign decision

The continuation results are not safe for strategy redesign. There is no event-level
denominator, no validation or holdout evidence, no feature-effect estimate, and no gate
pass/fail outcome comparison. The label protocol may be reused for a future governed
cohort, but the present empirical result must not be used to change thresholds or
strategy semantics.

`BREAKOUT_EVENT_DEFINITION_AUTHORITATIVE: YES`

`CONTINUATION_LABELS_PIT_SAFE: YES`

`TEMPORAL_V3_PREDICTS_CONTINUATION: NO`

`ROOT_RETENTION_PREDICTS_CONTINUATION: NO`

`COST_MIGRATION_PREDICTS_CONTINUATION: NO`

`PEAK_PERSISTENCE_PREDICTS_CONTINUATION: NO`

`ENSEMBLE_AGREEMENT_PREDICTS_CONTINUATION: NO`

`CURRENT_RETEST_GATES_HAVE_DISCRIMINATIVE_VALUE: NO`

`SAFE_TO_USE_CONTINUATION_RESULTS_FOR_REDESIGN: NO`
