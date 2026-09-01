# V3 Falling-Knife Risk Methodology and Outcome-Blind Freeze

This document freezes V3 before the broad outcome-bearing run. The choices below are based
only on the authoritative V1/V2 implementation, causal OHLC/preclose semantics, economic
meaning, simplicity, and a small outcome-blind feature-validation slice. No V3 forward MAE,
return, MFE, or future-trigger outcome was inspected when these definitions were selected.

## Frozen carrier, event, and chronology

V3 reuses the exact V2 primary carrier and cohort infrastructure without changing a threshold:

- exact V1 LOW eligibility, liquidity, hard-valid, lineage, and recent-low rules;
- causal adjusted-close drawdown from the trailing 60-session high `<= -30%` at t0 close;
- a de-duplicated event is the first carrier observation after no carrier observation in the
  prior 20 trading rows; and
- the same legal next-session-open entry and complete clean 25-session V2 horizon rules.

`t0` is the original causal deep-carrier event date. V3 features end at t0 close. Immediate
Ret20, MFE20, and MAE20 retain V2's next-legal-open chronology and adjusted 20-session path.
The primary label is exactly `MAE20 <= -10%`. Future V2 trigger status is joined only after
the feature score has been constructed and is used only as a secondary diagnostic outcome.

## Frozen t0 price-state features

All four variables are oriented so larger means more dangerous.

1. **Close-location danger:**
   `1 - (close_t0 - low_t0) / (high_t0 - low_t0)`.
   It is zero at the high and one at the low. A zero-range day is unavailable and fails
   closed; it is not assigned an invented neutral value.
2. **Current-day loss danger:**
   `-(close_t0 / preclose_t0 - 1)`.
   A larger value means a more adverse t0 close-to-preclose shock.
3. **Five-session negative-day persistence:**
   the count of sessions with `close / preclose - 1 < 0` over t0-4 through t0, inclusive.
   The required history is complete and causal. Larger counts mean more persistent selling.
4. **Adverse-gap danger:**
   `-(open_t0 / preclose_t0 - 1)`.
   A larger value means a more adverse overnight repricing into t0.

The family deliberately omits technical-indicator grids, volume, fundamentals, news, fitted
models, and alternative lookback searches. It does not reinterpret V1 crash speed as a return
factor; five-day negative-session persistence is tested only as a tail-risk descriptor.

## Frozen equal-weight score

For every date and feature, compute `percent_rank` among **all contemporaneous, causally valid
deep-carrier observations** with complete t0 features. This rank universe is formed before
event de-duplication and before any future-outcome availability filter. Each component rank is
therefore in `[0,1]`, uses only information observable by that date's close, and has the same
danger orientation.

The frozen composite is:

`risk_score = (CLV_rank + daily_loss_rank + persistence_rank + gap_rank) / 4`.

There are no fitted weights, feature selection, or outcome-dependent transformations. The
primary event table joins this already-constructed score to the exact V2 event/outcome table.

## Frozen descriptive analyses

- Continuous features and the composite use pooled event quintiles, `Q1` safest through `Q5`
  most dangerous. The discrete persistence feature uses fixed bins: 0-1, 2, 3, 4, and 5
  negative sessions. These bins are descriptive, not production thresholds.
- The simplest constituent baseline is close-location danger.
- Calendar/depth conditioning uses equal-weight date x fixed drawdown-cell comparisons. The
  fixed depth cells are `[-35%,-30%]`, `[-40%,-35%)`, `[-45%,-40%)`, and `<-45%`; cells need
  at least six events and compare within-cell danger terciles.
- Highest-risk 10%, 20%, and 30% cuts use fixed requested fractions of the full event sample,
  ordered by the frozen score with symbol/date tie-breaks. These are explicitly
  **descriptive policy analyses** because their full-sample score cutoffs are not deployable
  thresholds.
- A skipped event earns 0% cash in opportunity-level policy return. Trade-conditional metrics
  are reported separately. A large winner is frozen as immediate Ret20 `>= +10%`.
- Broad periods are 2020, 2021-2023, and 2024-2026. Liquidity retains V2's pooled thirds. The
  PIT-industry sanity check uses within-industry composite percentiles; market-segment results
  are descriptive when available.

## Outcome-blind semantic validation

A twelve-symbol slice produced 157 deep observations. Every row had positive high-low range,
valid open/preclose semantics, and a complete five-session history; CLV ranged from 0 to 1.
The inspected feature values used only t0 and preceding rows. This validated formulas and
coverage only; no V3 outcome or future-trigger field was selected or viewed.

## Interpretation boundary

V3 asks whether observable t0 price state predicts future severe adverse excursion while
preserving the frozen deep-oversold carrier. Ret20 is secondary. No weak variable will be
replaced after the broad run, and V3 will stop after choosing one of the four mandated verdicts.
