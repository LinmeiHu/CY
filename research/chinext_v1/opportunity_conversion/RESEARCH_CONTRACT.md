# Research Contract

## 1. Immutable strategy and prior evidence

Authoritative CHINEXT V1 strategy code and semantics remain unchanged.

- Strategy SHA256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Prior final report SHA256:
  `e1ddd39c110f4b3774995f2c217cb5943462de47b2c2949ce996ed6d8bec5af3`
- Prior Phase 8 report SHA256:
  `a223c25466b4ac1577404fbe27d1a700b9d5e9dcdd5d290ebe38172753f16591`
- Prior Phase 9 report SHA256:
  `d44cd0be6207154945c3ae7f389740602963f8a95e4b4e0b076af377ec80d79b`
- Frozen Phase 2 market-feature artifact SHA256:
  `5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6`

The three replay blocks remain independent bounded diagnostics:

- EXTENDED: 2018-2021;
- HOLDOUT O0: 2022-2023;
- DEVELOPMENT: 2024-2025.

They must never be chained into a continuous NAV. All evidence is bounded
PIT-B unless an experiment explicitly proves a stronger standard. There is no
untouched OOS block for a newly invented rule.

## 2. Non-negotiable correctness rules

1. Do not change authoritative V1, its exits, fills, sizing, costs, or signals.
2. No information available after `decision_at` may enter a claimed predictor.
3. Preserve T+1 and actual execution timing. Outcome-path diagnostics may use
   future data only when labeled hindsight/oracle.
4. Preserve asset registry, snapshot, lineage, and PIT fail-closed behavior.
5. Do not normalize, clip, or round away accounting or path discrepancies.
6. Never silently substitute a missing input.
7. Existing dirty-worktree changes are preserved and not attributed to this
   goal unless this goal explicitly creates them.

## 3. Authoritative trade universe

The primary universe is the 399 completed authoritative V1 cycles in
`regime_attribution/artifacts/yearly_trades.csv`, reconciled to their
independent replay blocks. Cycle IDs, entry/exit dates, capital, P&L, and
terminal return are inherited. Any cycle lost during enrichment is a hard
failure, not an ignorable missing value.

Stock-level entry inputs are limited first to the existing causal V1 fields:

- RS score;
- MOM20, MOM60, MOM120;
- box width;
- volume ratio;
- MINVOL location and ratio;
- breakout-volume ratio.

New predictors require a separate preregistration after these assets are
exhausted.

## 4. Frozen metric definitions

Definitions below are fixed before new outcomes are calculated.

### 4.1 Returns and holding path

- `terminal_return`: inherited exact round-trip return, including authoritative
  execution and cost treatment.
- Holding path starts at entry execution and ends at exit execution.
- On ordinary holding sessions, total-return-adjusted high, low, and close are
  eligible outcome observations.
- On the exit session, only the actual exit execution price is eligible;
  later intraday prices on that session are excluded.
- `MFE`: maximum eligible high return versus entry execution price.
- `MAE`: minimum eligible low return versus entry execution price.
- `time_to_MFE` / `time_to_MAE`: trading-session offsets from entry execution,
  with entry session equal to zero.
- `time_to_MFE_fraction`: `time_to_MFE / max(1, holding_trading_days)`, where
  inherited `holding_trading_days` is the number of session intervals from
  entry execution to exit execution.
- `peak_close_return`: maximum eligible close/exit return during the hold.
- `post_MFE_giveback`: `MFE - terminal_return`, never clipped.
- `post_peak_close_giveback`: `peak_close_return - terminal_return`, never
  clipped.

MFE uses an intraday high and is not a realizable sale price. It is opportunity
availability, not tradable P&L.

### 4.2 Conversion and capture

- Primary opportunity: `MFE >= 20%`.
- Extreme opportunity sensitivity: `MFE >= 50%`.
- `MFE_realization`: `terminal_return / MFE`, reported only where `MFE > 0`
  and never clipped.
- `opportunity20_capture`: `terminal_return / MFE` for `MFE >= 20%`.
- `winner_capture`: same ratio for terminal right-tail winners.
- `positive_capture`: `terminal_return > 0` conditional on an opportunity.
- `right_tail_conversion20`: `terminal_return >= 20%` conditional on
  `MFE >= 20%`.
- `extreme_conversion50`: `terminal_return >= 50%` conditional on
  `MFE >= 50%`.
- `post_peak_decay_rate`:
  `(peak_close_return - terminal_return) / max(1, days_from_peak_to_exit)`;
  sign is retained.

### 4.3 Mutually exclusive terminal classes

- `extreme_winner`: terminal return `>= 50%`;
- `right_tail_winner`: `20% <= return < 50%`;
- `ordinary_winner`: `2% < return < 20%`;
- `flat`: `-2% <= return <= 2%`;
- `small_loser`: `-10% < return < -2%`;
- `severe_loser`: return `<= -10%`.

The inherited severe-loss `<= -10%`, extreme-winner `>= 50%`, opportunity20,
opportunity50, and false-breakout definitions remain primary. An inherited
false breakout is `MFE < 10% and terminal_return <= 0`.

Neighboring-definition sensitivity is limited to preregistered checks, not a
threshold search:

- flat band: +/-1%, +/-2%, +/-3%;
- opportunity: 15%, 20%, 25%;
- extreme opportunity/winner: 40%, 50%, 60%;
- severe loss: -8%, -10%, -12%;
- false-breakout MFE ceiling: 8%, 10%, 12%.

### 4.4 Frozen path descriptors

All path descriptors are outcomes and cannot be used as entry-time predictors.

- `pre_MFE_MAE`: minimum eligible low return from entry through the MFE
  session, inclusive.
- `pre_peak_direction_efficiency`: absolute close-path displacement from entry
  session close to maximum-close session divided by total absolute close-path
  variation over that interval; zero when the denominator is zero.
- `pre_peak_positive_day_fraction`: fraction of close-to-close changes above
  zero from entry through maximum-close session; missing if no changes exist.
- `pre_peak_max_drawdown`: minimum drawdown from the running maximum of the
  eligible close-return index before the maximum-close session.
- `post_peak_positive_day_fraction`: fraction of close-to-close changes above
  zero after the maximum-close session through exit; missing if no changes.
- `holding_path_mean_close_return`: arithmetic mean of eligible daily close
  returns versus entry price.

No smoothing, winsorization, or clipping is permitted in primary results.

### 4.5 Market-state changes during a hold

Entry market context is the completed entry-signal-session feature joined by
the inherited PIT rule. For a path event occurring on session `t`, its market
context uses the last completed market feature strictly before that event,
normally session `t-1`. Same-session breadth after an intraday peak must not be
described as a predictor of that peak.

Primary breadth is continuous `breadth_above_ma20`; ranks and terciles are
descriptive only. No exposure threshold optimization is allowed.

## 5. Opportunity supply versus selected-trade quality

Selected-trade quality is measured on the 399 cycles. Candidate supply may be
measured only if an existing authoritative event ledger exposes a stable,
reconciled candidate/evaluation count with documented semantics. Candidate
events must not be conflated with completed trades or opportunity20 outcomes.
If supply cannot be reconstructed identically across blocks, the question is
reported as unresolved rather than filled by a proxy.

## 6. Counterfactual and oracle boundary

Oracle diagnostics may bound lost opportunity but cannot support a tradable
claim.

Allowed diagnostic ceilings:

- perfect terminal-sign selection on the fixed trade ledger;
- perfect right-tail selection on the fixed trade ledger;
- `capital * (MFE - terminal_return)` as an initial-capital MFE ceiling;
- post-exit 5/10/20-session total-return paths from actual exit execution,
  when explicitly generated and coverage-audited;
- already-frozen authoritative exit-ablation and winner-hold experiments.

The first three ignore portfolio crowding, vacancy, resizing, fill feasibility,
and alternate-path feedback. They are not NAVs and are non-additive. MFE is an
intraday-high oracle. Post-exit paths use future outcomes and are never causal
features.

A realistic candidate must instead be observable at its own decision time and
must be replayed through authoritative execution semantics. Existing 2024-2025
exit ablations and the failed 2022-2023 winner-hold OOS test remain frozen
counterevidence.

## 7. Statistical hierarchy and robustness

The primary estimands are effect signs, rank association, class rate
differences, and economically interpretable return/P&L decomposition. For
each claimed relationship audit:

- full-sample magnitude and sample count;
- yearly sign and magnitude;
- rolling windows;
- leave-one-year-out;
- neighboring definitions;
- monotonicity or plateau behavior;
- top-N dependence;
- removal of each extreme trade and/or top contributors;
- multiple-testing family and exploratory status;
- PIT and missingness coverage.

Eight yearly signs alone are not independent OOS validation. LOYO is a
stability diagnostic. With no untouched period, any new candidate evidence is
at most bounded OOS/LOYO unless a new held-out asset is explicitly frozen
before use.

## 8. Mechanism gate

A conversion leakage is considered established only if it has:

1. a frozen economic definition;
2. material magnitude, not only a p-value;
3. stable direction across years and LOYO;
4. robustness to neighboring definitions and extreme-trade removal;
5. adequate sample support; and
6. a clear location in the attribution chain.

Outcome path variables may establish where leakage occurs, but not whether it
is predictable at entry or exit.

## 9. Strategy-design gate

No candidate may be designed until mechanism attribution is complete. A
minimum sufficient candidate is allowed only if the proposed decision
variable:

1. is available at its decision timestamp;
2. is stable across years;
3. is LOYO-stable;
4. is not dependent on a narrow threshold;
5. has a clear economic mechanism;
6. survives costs, coverage, exposure normalization, and extreme-trade tests;
7. does not contradict frozen OOS evidence; and
8. adds the least possible complexity.

Priority is entry refinement, then winner retention/exit refinement, then
conditional holding, then a combination. Black-box ML and renewed breadth
threshold search are prohibited.
