# Reverse Exit Study V1

## Result

Canonical temporal V3 contains **mixed, research-level warning information** before
future drawdowns in objectively defined price uptrends. The strongest replicated
directional result is tracked-peak mass/prominence deterioration. Rolling-base loss,
rebinding, concentration deterioration, profit-ratio reversal, and split/merge/lost
topology also carry some warning information, but their false-warning and hypothetical
premature-exit rates are too high for exit redesign.

The requested primary production cohort does not exist in this governed replay. The
authoritative 500-stock ledger contains zero qualified entries, zero filled entries,
zero open holdings, and zero exit conditions, intents, attempts, blocks, deferrals, or
fills. Exact root-retention deterioration and current production exit-timing efficiency
are therefore not estimable. No rolling-base proxy is substituted for the immutable
strategy root.

This study does not define, select, or optimize a replacement exit strategy. Its results
are not safe to use directly for exit redesign.

## Governed scope and provenance

- Branch: `research/v12-reverse-exit-study`
- Baseline: `f502367049ad291dc703c63fdd594798171c9e97`
- Frozen bundle: `v12-v3-500-temporal-2020`
- Symbols / rows / dates: 500 / 121,251 / 2020-01-02 through 2020-12-31
- Frozen root manifest SHA-256:
  `915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a`
- Frozen tree attestation: 13,479 files, 4,287,243,945 bytes,
  `e33fb84ecabfd33f8bb357569a1d57086ac2acf4d201c00e4e2b5d61aa085d91`
- Authoritative ledger manifest SHA-256:
  `4b4ba0325f41dfcda5f9a7e8e3f259907dbf596f5b2863f622bf2503c7e30254`
- Ledger schema / parameter:
  `v12-lifecycle-entry-exit-ledger-v1` / `9baed76ec299161c`
- Ledger lifecycle / gate / execution / summary rows:
  121,252 / 555,418 / 0 / 1
- Ledger lifecycle PIT violations: 0
- Frozen feature duplicate keys / missing required snapshot rows / feature PIT
  violations: 0 / 0 / 0
- Research-valid V3 rows: 120,472; tracked-base rows: 41,619

Outcome prices, volume, and turnover come only from the immutable CY-006 daily
inventory explicitly bound by the authoritative ledger manifest. The verified
inventory SHA-256 is
`de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.
The verified 2020 price partition is
`1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62`.
The verified 2019 partition
`c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd`
is used only as backward-looking price warm-up for the first 2020 uptrend decisions;
it supplies no outcome label.

No chip state, checkpoint, journal, panel, or ledger was rebuilt. No full-market input
was read. No production strategy or exit semantics were changed.

## Protocol frozen before outcome inspection

### Chronological partitions

The 243 market sessions are split into equal chronological thirds. Past-only warm-up
may precede a split, but no future label crosses a split boundary.

| Partition | Dates | Market sessions | Uptrend decisions | Tracked-base uptrend decisions |
|---|---|---:|---:|---:|
| Discovery | 2020-01-02 to 2020-05-07 | 81 | 5,099 | 1,499 |
| Validation | 2020-05-08 to 2020-09-01 | 81 | 5,124 | 1,563 |
| Holdout | 2020-09-02 to 2020-12-31 | 81 | 3,281 | 912 |

Thresholds were fixed without looking at outcome relationships. Discovery,
validation, and holdout all report the same indicators; no later-period threshold was
changed.

### PIT-safe decision population

An objective uptrend is present at decision time when all of the following are known:

1. close is above the trailing 60-session mean;
2. trailing 20-session close return is at least +10%;
3. close is within 10% of the trailing 20-session close high;
4. the V3 row is `research_valid`;
5. all required price, trading-state, historical-identity, and corporate-action
   snapshots in the 60-session lookback are valid and available.

This defines a secondary research population, not a production entry or simulated
holding.

### Outcome labels

All future windows begin at T+1. No bar-t feature uses bar-t+1 or later data.

- Current-close drawdown: minimum future close divided by the decision close minus one,
  at 5, 10, 20, 40, and 60 future sessions; thresholds are -5%, -10%, -15%, and -20%.
- Support failure: any future close below the decision-time canonical tracked-base band
  lower bound.
- Local-high drawdown: minimum future close relative to the trailing 20-session close
  high, reported at -10% and -15%.
- Material drawdown episode for warning coverage: first close at least 10% below the
  trailing 20-session close high, with the episode reset only after recovery inside 5%
  of that high. The episode must have an objective uptrend in the prior 20 sessions.

A label is unknown and excluded unless the complete future horizon remains inside its
chronological partition and every required future price/trading/corporate-action lineage
check passes. Any window containing a corporate action is excluded instead of treating
an unadjusted price-coordinate change as a drawdown.

### Warning metrics

- Warning lead: sessions from the nearest prior warning onset to the material drawdown
  episode, using a maximum 20-session warning lookback and excluding same-day warnings.
- Drawdown coverage: material drawdown episodes with at least one prior warning onset.
- False-warning rate: warning onsets not followed by a -10% current-close drawdown in
  the next 20 sessions.
- Profitable trend prematurely exited: warning onsets for which +10% is reached before
  -10% during the next 20 sessions. This is a diagnostic counterfactual only; no exit is
  simulated.
- Risk lift: 20-session -10% drawdown rate on warning onsets divided by the rate on all
  eligible uptrend decisions in that partition.

The material drawdown episode denominators are 461 discovery, 379 validation, and 264
holdout episodes. Baseline 20-session -10% drawdown rates are 73.4%, 24.3%, and 38.6%,
respectively. The discovery period is dominated by the early-2020 crash, so lift and
cross-period replication matter more than its raw false-warning rate.

## Future deterioration outcomes

Each rate is the percentage of eligible objective-uptrend decisions whose minimum
future close breaches the stated threshold. `N` is the complete, action-clean label
count.

| Horizon | Discovery N | -5 / -10 / -15 / -20% | Validation N | -5 / -10 / -15 / -20% | Holdout N | -5 / -10 / -15 / -20% |
|---:|---:|---|---:|---|---:|---|
| 5 | 4,810 | 44.2 / 20.3 / 7.3 / 2.0% | 4,730 | 35.7 / 9.6 / 2.6 / 0.4% | 3,037 | 33.9 / 7.3 / 2.2 / 0.8% |
| 10 | 4,491 | 68.1 / 46.3 / 23.6 / 8.5% | 4,268 | 48.8 / 18.1 / 5.6 / 1.8% | 2,830 | 53.0 / 19.4 / 5.6 / 1.5% |
| 20 | 3,989 | 87.0 / 73.4 / 48.0 / 24.0% | 3,443 | 56.3 / 24.3 / 9.1 / 3.6% | 2,357 | 67.9 / 38.6 / 14.6 / 5.3% |
| 40 | 3,098 | 91.7 / 82.8 / 61.6 / 36.3% | 1,243 | 61.1 / 29.4 / 12.2 / 5.2% | 962 | 73.9 / 49.5 / 30.9 / 15.6% |
| 60 | 1,721 | 92.9 / 86.5 / 69.5 / 44.6% | 456 | 74.6 / 43.2 / 19.7 / 9.0% | 365 | 89.9 / 65.8 / 43.6 / 28.8% |

Support and local-high outcomes show the same strong horizon and regime dependence.
Support cells show `eligible N / failure rate`; local-high cells use the main eligible
N above.

| Horizon | Discovery support | Validation support | Holdout support | Local-high -10% D / V / H | Local-high -15% D / V / H |
|---:|---|---|---|---|---|
| 5 | 1,413 / 29.1% | 1,430 / 30.4% | 853 / 14.7% | 31.2 / 21.6 / 19.1% | 14.5 / 6.3 / 4.7% |
| 10 | 1,331 / 42.8% | 1,293 / 33.1% | 809 / 20.3% | 55.5 / 32.6 / 35.4% | 33.8 / 11.0 / 11.9% |
| 20 | 1,191 / 58.0% | 1,048 / 36.1% | 690 / 26.2% | 79.6 / 39.5 / 51.4% | 59.4 / 14.8 / 26.3% |
| 40 | 957 / 66.9% | 337 / 39.5% | 271 / 26.2% | 86.0 / 41.7 / 61.3% | 68.9 / 18.4 / 37.5% |
| 60 | 570 / 71.2% | 111 / 28.8% | 88 / 37.5% | 88.0 / 55.0 / 83.6% | 75.4 / 24.3 / 59.2% |

## Current-feature warning definitions

All warning indicators use only the current and prior observations.

| Indicator | Outcome-blind definition |
|---|---|
| Exact root retention deterioration | Authoritative open-lifecycle exact-lineage gate only. It is not invoked in this replay because there are no entries or holdings. |
| Rolling-base loss | Prior session has a canonical tracked-base ID and the current session has none. |
| Rolling-base rebinding | Prior session has no tracked base and the current session has a new canonical tracked-base ID. |
| Peak mass deterioration | Same tracked ID after five sessions; current mass is at most 75% of its prior five-session maximum. |
| Prominence deterioration | Same tracked ID after five sessions; current prominence is at most 75% of its prior five-session maximum. |
| Peak age | Canonical tracked peak age reaches 120 sessions. |
| Band widening | Same tracked ID after five sessions; normalized band width is at least 125% of its prior five-session median. |
| Concentration deterioration | `concentration_20` falls at least 0.10 below its prior five-session maximum. |
| Profit saturation/reversal | Prior five-session profit ratio reaches 0.90 and current profit ratio is at most 0.75. |
| Seller-model disagreement | Maximum frozen seller-model price spread is at least 10% of average cost. This is a research indicator, not the production ATR gate. |
| Split / merge / lost | Canonical temporal V3 event booleans, reported separately. They may concern any ensemble peak, not only the tracked base. |
| Cost migration reversal | Average cost rises at least 3% from t-20 to t-5 and then falls at least 3% by t. |
| Distribution evidence | Current return at most -2%, profit ratio falls at least 0.15 from its prior five-session maximum, and average cost is below t-5. |
| Volume/turnover distribution | Current return at most -2%, with both volume and turnover at least 1.5 times their prior 20-session medians. |

## Per-signal results

`Eligible/total` is the number of warning onsets with a complete 20-session label
divided by all warning onsets in the objective uptrend cohort. Percent columns are
episode coverage, false-warning rate, and hypothetical profitable premature exits.
`N/E (0)` means the relationship with production exit reasons is not estimable because
the authoritative ledger has zero exit conditions and executions; it is not missing
ledger attribution.

### Discovery

| Signal/gate | Eligible / total | Median lead | Coverage | False | Premature | Risk lift | Production exit relation |
|---|---:|---:|---:|---:|---:|---:|---|
| Exact root retention deterioration | 0 / 0 | N/E | N/E | N/E | N/E | N/E | N/E (0) |
| Rolling-base loss | 277 / 345 | 5.0 | 37.1% | 25.6% | 22.7% | 1.01 | N/E (0) |
| Rolling-base rebinding | 267 / 335 | 5.0 | 34.9% | 27.0% | 24.3% | 1.00 | N/E (0) |
| Peak mass deterioration | 55 / 63 | 7.0 | 6.1% | 12.7% | 29.1% | 1.19 | N/E (0) |
| Prominence deterioration | 46 / 51 | 8.0 | 5.0% | 26.1% | 34.8% | 1.01 | N/E (0) |
| Peak age >=120 | 251 / 312 | 7.0 | 10.6% | 21.5% | 14.7% | 1.07 | N/E (0) |
| Band widening | 23 / 29 | 3.5 | 2.6% | 8.7% | 4.3% | 1.24 | N/E (0) |
| Concentration deterioration | 495 / 582 | 2.0 | 29.9% | 25.7% | 27.3% | 1.01 | N/E (0) |
| Profit saturation/reversal | 250 / 307 | 1.0 | 26.7% | 24.8% | 22.4% | 1.03 | N/E (0) |
| Seller-model disagreement | 1,190 / 1,455 | 3.0 | 49.0% | 23.6% | 23.4% | 1.04 | N/E (0) |
| Split | 637 / 787 | 4.0 | 55.1% | 22.9% | 24.3% | 1.05 | N/E (0) |
| Merge | 903 / 1,115 | 4.0 | 64.2% | 24.9% | 26.0% | 1.02 | N/E (0) |
| Lost | 1,123 / 1,396 | 3.0 | 77.0% | 26.2% | 27.1% | 1.01 | N/E (0) |
| Cost migration reversal | 0 / 0 | N/E | 0.0% | N/E | N/E | N/E | N/E (0) |
| Distribution evidence | 36 / 43 | 5.0 | 6.1% | 5.6% | 11.1% | 1.29 | N/E (0) |
| Volume/turnover distribution | 286 / 354 | 2.0 | 43.4% | 22.4% | 18.9% | 1.06 | N/E (0) |

### Validation

| Signal/gate | Eligible / total | Median lead | Coverage | False | Premature | Risk lift | Production exit relation |
|---|---:|---:|---:|---:|---:|---:|---|
| Exact root retention deterioration | 0 / 0 | N/E | N/E | N/E | N/E | N/E | N/E (0) |
| Rolling-base loss | 275 / 387 | 7.0 | 45.1% | 73.5% | 43.6% | 1.09 | N/E (0) |
| Rolling-base rebinding | 257 / 376 | 7.0 | 43.5% | 74.3% | 49.4% | 1.06 | N/E (0) |
| Peak mass deterioration | 48 / 79 | 6.0 | 7.7% | 70.8% | 41.7% | 1.20 | N/E (0) |
| Prominence deterioration | 28 / 57 | 4.5 | 6.3% | 64.3% | 35.7% | 1.47 | N/E (0) |
| Peak age >=120 | 176 / 256 | 7.0 | 9.2% | 86.9% | 48.9% | 0.54 | N/E (0) |
| Band widening | 27 / 43 | 7.0 | 3.7% | 74.1% | 44.4% | 1.07 | N/E (0) |
| Concentration deterioration | 349 / 552 | 2.0 | 35.4% | 49.3% | 47.3% | 2.09 | N/E (0) |
| Profit saturation/reversal | 141 / 251 | 1.0 | 25.9% | 68.8% | 46.8% | 1.28 | N/E (0) |
| Seller-model disagreement | 1,425 / 2,005 | 4.0 | 65.2% | 76.2% | 44.1% | 0.98 | N/E (0) |
| Split | 558 / 795 | 5.0 | 63.6% | 68.5% | 46.8% | 1.30 | N/E (0) |
| Merge | 772 / 1,082 | 4.0 | 71.8% | 68.4% | 43.8% | 1.30 | N/E (0) |
| Lost | 964 / 1,394 | 3.0 | 81.3% | 67.0% | 42.9% | 1.36 | N/E (0) |
| Cost migration reversal | 0 / 0 | N/E | 0.0% | N/E | N/E | N/E | N/E (0) |
| Distribution evidence | 27 / 29 | 3.0 | 4.5% | 81.5% | 33.3% | 0.76 | N/E (0) |
| Volume/turnover distribution | 275 / 399 | 3.5 | 57.5% | 69.5% | 42.2% | 1.26 | N/E (0) |

### Holdout

| Signal/gate | Eligible / total | Median lead | Coverage | False | Premature | Risk lift | Production exit relation |
|---|---:|---:|---:|---:|---:|---:|---|
| Exact root retention deterioration | 0 / 0 | N/E | N/E | N/E | N/E | N/E | N/E (0) |
| Rolling-base loss | 136 / 197 | 7.0 | 33.7% | 55.9% | 31.6% | 1.14 | N/E (0) |
| Rolling-base rebinding | 127 / 190 | 7.0 | 31.4% | 48.8% | 34.6% | 1.33 | N/E (0) |
| Peak mass deterioration | 29 / 39 | 8.0 | 4.9% | 34.5% | 24.1% | 1.70 | N/E (0) |
| Prominence deterioration | 22 / 30 | 2.0 | 3.4% | 27.3% | 27.3% | 1.89 | N/E (0) |
| Peak age >=120 | 70 / 90 | 9.5 | 4.5% | 70.0% | 47.1% | 0.78 | N/E (0) |
| Band widening | 16 / 24 | 4.5 | 4.5% | 50.0% | 43.8% | 1.30 | N/E (0) |
| Concentration deterioration | 217 / 337 | 4.0 | 25.4% | 49.8% | 33.6% | 1.30 | N/E (0) |
| Profit saturation/reversal | 124 / 190 | 4.0 | 26.9% | 50.0% | 36.3% | 1.30 | N/E (0) |
| Seller-model disagreement | 707 / 976 | 5.0 | 47.3% | 62.8% | 32.8% | 0.96 | N/E (0) |
| Split | 309 / 446 | 5.0 | 50.0% | 54.0% | 33.3% | 1.19 | N/E (0) |
| Merge | 434 / 634 | 5.0 | 61.4% | 52.3% | 32.7% | 1.24 | N/E (0) |
| Lost | 556 / 841 | 5.5 | 71.2% | 53.6% | 32.6% | 1.20 | N/E (0) |
| Cost migration reversal | 0 / 0 | N/E | 0.0% | N/E | N/E | N/E | N/E (0) |
| Distribution evidence | 3 / 10 | 4.5 | 1.5% | 100.0% | 33.3% | 0.00 | N/E (0) |
| Volume/turnover distribution | 175 / 238 | 7.0 | 43.2% | 62.9% | 34.9% | 0.96 | N/E (0) |

## Authoritative production attribution

The ledger cleanly distinguishes every requested production stage, but each count is
zero in the governed data:

| Production stage | Authoritative count |
|---|---:|
| Entry qualification / intent / fill | 0 / 0 / 0 |
| Open holding state | 0 |
| Exit condition | 0 |
| Exit intent | 0 |
| Exit execution attempt | 0 |
| Blocked or deferred exit | 0 |
| Actual exit fill | 0 |

The sole lifecycle is `000709.SZ`, rooted on 2020-12-18. It remains
`ACCUMULATING` through year-end, has nine rejected breakout observations, and never
qualifies or enters. It supplies no root-retention holding episode and no exit-timing
comparison. Therefore:

- existing production exits cannot be compared with counterfactual indicators;
- no signal can be related to protective-stop, root-failure, distribution-confirmation,
  max-holding, or execution-block reason in real production holdings;
- zero is an authoritative observation, not permission to fabricate positive exit paths
  from unit-test fixtures.

## Findings

1. **Tracked mass and prominence deterioration are the clearest low-coverage warning.**
   Validation risk lifts are 1.20 and 1.47; holdout lifts are 1.70 and 1.89. Holdout
   median leads are 8 and 2 sessions, false-warning rates are 34.5% and 27.3%, and
   hypothetical premature-exit rates are 24.1% and 27.3%. But holdout coverage is only
   4.9% and 3.4%, with just 29 and 22 complete warning labels. This is useful
   descriptive evidence, not an exit gate.

2. **Rolling-base loss and rebinding warn broadly but are not selective enough.**
   Loss has validation/holdout lift 1.09/1.14 and 45.1%/33.7% coverage; rebinding has
   lift 1.06/1.33 and 43.5%/31.4% coverage. Their false-warning rates are
   73.5%/55.9% and 74.3%/48.8%, while profitable premature-exit rates are
   43.6%/31.6% and 49.4%/34.6%. A rolling topology transition is context, not a
   sufficient exit condition.

3. **Concentration deterioration and profit-ratio reversal replicate directionally.**
   Concentration lift is 2.09 validation and 1.30 holdout; profit reversal is 1.28 and
   1.30. Both retain roughly 25–35% event coverage, but approximately half of holdout
   warnings are false and one third of warned trends reach +10% before -10%.

4. **Split, merge, and lost favor recall over precision.** Lost covers 81.3% of
   validation and 71.2% of holdout drawdown episodes, with median leads of 3 and 5.5
   sessions. Validation/holdout lifts are only 1.36/1.20, false-warning rates are
   67.0%/53.6%, and premature-exit rates are 42.9%/32.6%. The flags may concern any
   ensemble peak, explaining part of their breadth.

5. **Seller-model disagreement does not validate as an exit warning.** Despite high
   coverage, its validation/holdout lifts are 0.98/0.96. The frozen research spread is
   common but not discriminative at the fixed 10%-of-cost threshold.

6. **Peak age, band widening, cost reversal, distribution, and volume/turnover do not
   establish a robust standalone warning.** Stale age is inversely related to drawdown
   in validation and holdout. Band widening is too sparse. The fixed cost-reversal gate
   fires zero times. The distribution composite and volume/turnover signal do not
   replicate in holdout.

7. **Exact root-anchor retention and production exit efficiency remain unknown.** The
   authoritative data have no entered lifecycle. The rolling structural base is not
   the immutable lifecycle root and is not used as a substitute.

## Limitations and use boundary

- This is one 2020 frozen 500-symbol research replay, with strong macro-regime changes
  and serially dependent symbol-days. Metrics are descriptive; no IID significance
  claim is made.
- Only 29.4% of objective-uptrend rows have a canonical tracked base, limiting the
  mass/prominence/support cohorts.
- The authoritative production ledger is exact but empty for entries and exits. That
  prevents the primary causal holding-state question from being answered here.
- The study measures warning behavior, not executable exits. It does not apply T+1
  sell fills, limit-down blocking, transaction costs, or portfolio interactions to a
  counterfactual strategy because doing so would redesign exits.
- The fixed research indicators are intentionally not optimized. Sparse or zero signals
  are reported rather than relaxed.

`MIXED` below includes irreducibly indeterminate primary evidence when the required
authoritative production cohort has zero observations; it must not be read as a positive
exit-design recommendation.

EXIT_OUTCOME_LABELS_PIT_SAFE: YES

PRODUCTION_EXIT_ATTRIBUTION_AUTHORITATIVE: YES

TEMPORAL_V3_PROVIDES_DRAWDOWN_WARNING: MIXED

ROOT_RETENTION_DERIORATION_HAS_EXIT_SIGNAL: MIXED

ROLLING_BASE_LOSS_HAS_EXIT_SIGNAL: MIXED

PEAK_MASS_PROMINENCE_DETERIORATION_HAS_SIGNAL: MIXED

ENSEMBLE_DISAGREEMENT_HAS_EXIT_SIGNAL: NO

CURRENT_PRODUCTION_EXIT_TIMING_EFFICIENT: MIXED

SAFE_TO_USE_EXIT_RESULTS_FOR_REDESIGN: NO
