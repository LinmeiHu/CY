# Hypothesis ledger

These hypotheses were frozen before the new unified 2018-2025 analysis, but after
prior repository reports had already exposed period outcomes. They are therefore
`PREREGISTERED_FOR_NEW_ANALYSIS`, not untouched pre-outcome hypotheses.

| ID | Hypothesis | Primary observable test | Initial status |
|---|---|---|---|
| H-001 | Cross-year V1 differences are dominated by the frequency and magnitude of right-tail winners, not by ordinary-trade median changes alone. | Annual Top-5/10/20 contribution, ex-best-N P&L, tail probabilities, median/mean decomposition. | AMBIGUOUS; prior evidence supportive |
| H-002 | Bad years combine right-tail scarcity with a lower win rate and more adverse entry/early holding paths; severe-loss frequency alone is insufficient. | Annual severe-loss rate, MFE/MAE, early continuation, payoff ratio, profit factor. | AMBIGUOUS; prior evidence supportive |
| H-003 | Medium-horizon market trend level/persistence predicts V1 top-winner probability more reliably than the binary existing MA20 entry gate. | Continuous/binned index momentum, MA distance/slope/persistence versus top-winner and severe-loss outcomes. | AMBIGUOUS; prior evidence supportive |
| H-004 | Broad participation and breadth persistence add information beyond index trend for identifying right-tail-capable environments. | PIT breadth continuous/quantile attribution, matched/conditional comparisons, coverage audit. | AMBIGUOUS; prior evidence inconclusive |
| H-005 | Fast rotation/leadership instability creates false breakouts: more small losses, weaker 5/10/20-day continuation, and fewer top winners. | PIT rank stability, winner persistence, breadth persistence/state flips versus trade paths. | AMBIGUOUS |
| H-006 | Cross-sectional dispersion/right-tail strength is a direct opportunity-set variable: positive asymmetry supports V1 while symmetric/downside dispersion does not. | PIT cross-sectional dispersion, skewness, upper/lower-tail fractions versus V1 outcomes. | AMBIGUOUS |
| H-007 | Volatility has a non-monotone interaction with trend/breadth: high volatility is beneficial only with positive persistent participation and harmful in weak/choppy states. | Univariate volatility followed only by supported Trend×Volatility/Breadth×Volatility interactions. | AMBIGUOUS |
| H-008 | Regime mainly affects entry opportunity quality and top-winner probability; exit inefficiency is secondary. | Regime×entry outcomes, holding path, exit lineage, MFE capture/giveback comparisons. | AMBIGUOUS; prior exit evidence mixed |
| H-009 | A simple exposure-only overlay can improve bad-year/severe-loss behavior more robustly than entry/exit adaptation, but may sacrifice rare top winners. | LOYO/walk-forward exposure candidate, top-winner capture, ex-best-N, exposure-normalized return, threshold sensitivity. | AMBIGUOUS |
| H-010 | If no coarse, stable PIT relationship survives LOYO and neighboring definitions, regime is explanatory only and V1-R should be rejected. | Predeclared robustness/falsification audit across all promoted candidates. | AMBIGUOUS |

## Do not promote without new evidence

- A year label is not a regime.
- The September 2024 winner cohort is not itself a rule.
- High breadth, high volatility, high RS, or high index momentum is not assumed
  beneficial without continuous and temporally stable evidence.
- Existing Phase 8 winner-hold is already rejected OOS and is not a default V1-R
  exit candidate.
- Industry, style, liquidity, or risk-appetite proxies are not assumed available
  until their PIT lineage and timestamp semantics pass audit.

## Status after EXP-P3-002

- H-003: `REJECTED` conditional on actual entries already passing the MA20 gate.
- H-004: `SUPPORTED_WITH_QUALIFICATION` for MFE/opportunity-path association;
  breadth incrementality over index trend remains unresolved.
- H-005: `REJECTED_CONTRADICTORY`; leadership turnover/overlap signs oppose the
  proposed fast-rotation false-breakout mechanism.
- H-006: `AMBIGUOUS_REFINE`; only the 20-day right-tail fraction survives.
- H-007: `AMBIGUOUS`; its conditional mechanism was not tested univariately.

After EXP-P4-002, H-004 is incrementally supported for MFE after fixed trend and
year controls, but remains qualified because MFE-to-realized-return conversion and
portfolio usefulness are unresolved.

## Status after EXP-P5-001

- H-004: `SUPPORTED_WITH_QUALIFICATION` as an incremental entry-opportunity
  descriptor; it is not a demonstrated downside gate or deployable rule.
- H-008: `AMBIGUOUS_BOTH_OPPORTUNITY_AND_CONVERSION_ASSOCIATED`. Breadth has
  stable MFE/opportunity and false-breakout associations. Raw conversion20 is
  weak, while capture/giveback signs are stable; fixed path/year/exit controls
  are required before deciding whether conversion adds independent information.
- H-009: `AMBIGUOUS_NOT_TESTED`. Phase 5 authorizes no exposure rule because no
  threshold, portfolio replay, or winner-sacrifice robustness test was run.

## Status after EXP-P6-001

- H-008: `SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION`. The raw
  capture/giveback association does not pass the one fixed path/year/exit-control
  model. This rejects an evidence-based exit adaptation while preserving the
  Phase 4/5 breadth-opportunity conclusion.
- H-009: `AMBIGUOUS_CANDIDATE_ELIGIBLE`. A simple exposure-only candidate may be
  tested because weak breadth has fewer favorable paths and more false breakouts,
  but breadth is not a severe-loss gate. The attribution-only full-year percentile
  composite is non-deployable and cannot be used as a V1-R rule.

## Status after EXP-P7-003

- H-009: `REJECTED_CANDIDATE`. The preregistered raw-breadth half-size rule fails
  its bad-environment and neighboring-definition gates. The primary rule leaves
  2022 unchanged, and the 0.30 neighbor also fails to improve 2022. It preserves
  most right-tail entries/P&L, but lower turnover and exposure do not establish
  a robust portfolio benefit. No neighboring arm may replace the primary after
  results.
- H-010: `SUPPORTED_PENDING_FORMAL_FALSIFICATION`. The candidate result already
  meets the central explanatory-only condition: no coarse stable overlay passes
  its frozen gates. Phase 8/9 will test whether rolling, temporal, activation,
  beta-timing, exposure-normalized, and implementation evidence contradicts that
  conclusion; no new candidate is authorized.

## Status after EXP-P8P9-001

- H-009: `REJECTED_ROBUSTNESS_FAILURE`. A40 improves 3 years, worsens 3, and is
  neutral in 2. All six block-by-126/252-session rolling gates fail, only 2/8
  within-block expanding prefixes improve, and all eight no-refit LOYO mean annual
  deltas are negative. Exposure-normalized return, fixed-neighbor, and ledger-cost
  gates also fail. Clean implementation and 90%+ right-tail retention do not
  offset the economic failures.
- H-010: `SUPPORTED_EXPLANATORY_ONLY`. Raw breadth is a qualified
  opportunity-path descriptor where coverage is valid, but neither the primary
  coarse exposure rule nor its neighboring definitions support a V1-R. Frozen V1
  remains the strategy; no production overlay is authorized.

## Status after resume integrity reconciliation

The EXP-P7-003 compatibility contract fails closed on a non-registry legacy Gate C
`replay_engine` hash mismatch. The exception in the frozen spec covers only the
append-extended registry. Therefore the Phase 7 result and all Phase 8/9
descendants are invalid evidence, even though their persisted files remain
byte-consistent with one another.

- H-008 remains `SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION` based
  only on valid EXP-P5-001/EXP-P6-001 evidence.
- H-009 returns to `UNRESOLVED_NOT_VALIDLY_TESTED`; the persisted candidate
  rejection must not be used.
- H-010 returns to `UNRESOLVED`. Explanatory-only/no-deployment remains the safe
  policy because no valid candidate evidence exists, not because the invalid
  Phase 7/8/9 branch proved rejection.

## Status at autonomous mechanism restart

- H-004 is `PROSPECTIVE_VALIDATION_PENDING`. Its historical breadth-opportunity
  conclusion is frozen. No threshold, overlay, exit adaptation, or additional
  historical interaction is authorized.
- H-011 is `REJECTED` by EXP-WLA-001.

### H-011 — pre-entry demand/compression transition

- Question: do extreme winners enter through a repeatable stock-level state
  transition rather than merely a high static V1 entry score?
- Mechanism: latent demand strengthens relative to 399102 while volatility,
  price range, and downside-session traded-amount share contract before the
  completed-close entry signal.
- Prediction: extreme-winner probability rises with T-20-to-T-1 relative-strength
  improvement and with at least one T-20-to-T-5 compression/supply contraction,
  after fixed V1 entry, year, market, breadth, beta, and liquidity controls.
- Required data: 399 frozen cycles; exact action-safe CY-006 stock history;
  QD-003 calendar; exact 399102 anchor; frozen entry and breadth artifacts.
- Primary test: four fixed continuous transitions, within-year ranks, BH over
  exactly four hypotheses, eight LOYO omissions, and one fixed residual design.
- Falsification: T-3 neighbors; block, security, industry, global Top-4 P&L,
  market/beta/volatility/liquidity, holding-duration/exit, PIT, and execution
  attacks.
- Metrics: raw and controlled rank association with the fixed >=50% extreme-winner
  outcome; >=20% winner, false-breakout, severe-loss, MFE, and terminal-return
  endpoints are secondary.
- Confounds: V1 already selects high RS/breakouts; all outcomes are consumed;
  PIT-B rather than PIT-A; only 15 extreme winners; down-session traded amount is
  not classified order flow.
- Result: none of the four primaries passed its raw gate. RS improvement rho was
  0.022 (controlled 0.018); volatility compression 0.001 (controlled 0.006);
  range compression -0.074 (controlled -0.090, contradictory); and downside-
  amount contraction 0.014 (controlled 0.003). BH q-values were 0.565..0.987.
  No component survived the fixed neighbor, LOYO, control, and falsification set.
- Status: `REJECTED`. Similar late acceleration appears across all outcome groups;
  this demand/compression transition does not distinguish V1's extreme winners.
