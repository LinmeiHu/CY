# CHINEXT V1 market-regime attribution goal

## Final objective

Systematically, comprehensively, and reproducibly explain why the authoritative
CHINEXT V1 behaves differently across years and market environments. Build a
strictly causal, point-in-time market-regime attribution framework and determine
whether a simple, robust, interpretable V1-R overlay can improve bad environments
without destroying V1's right-tail winner mechanism.

The research is successful even if the final verdict is negative. The objective is
credible mechanism and applicability evidence, not the best-looking backtest.

## Questions that must be answered

1. Why does V1 perform well in some years and poorly in others?
2. Which trend, breadth, volatility, dispersion, style, liquidity, risk-appetite,
   and rotation/persistence states explain those differences?
3. Which environments produce V1's right-tail super-winners?
4. Which environments produce small losses, severe losses, and false breakouts?
5. Does regime primarily affect entry quality, top-winner probability,
   severe-loss probability, holding path, exit efficiency, or exposure efficiency?
6. Is a simple PIT V1-R overlay worth deploying, and what does it improve or
   sacrifice relative to frozen V1?

## Definition of done

The goal is complete only after all of the following exist as reproducible,
lineage-bound artifacts:

1. authoritative baseline reconciliation;
2. yearly performance and distribution decomposition;
3. audited PIT market-regime feature library;
4. univariate attribution;
5. evidence-supported interaction analysis;
6. top-winner and severe-loss mechanism analysis;
7. regime-by-entry-cohort analysis;
8. regime-by-holding-path/exit analysis;
9. simple V1-R candidates, if mechanism evidence warrants them;
10. robustness, walk-forward/OOS where feasible, leave-one-year-out, and active
    falsification;
11. a clear final verdict; and
12. `FINAL_REPORT.md`, with FACT, EVIDENCE, INTERPRETATION, HYPOTHESIS,
    FAILED HYPOTHESIS, STRATEGY CANDIDATE, and UNRESOLVED explicitly separated.

## Non-negotiable constraints

- Preserve the authoritative V1 strategy, signals, trade definition, NAV
  definition, execution assumptions, T+1, limits, trading state, corporate
  actions, costs, and no-replacement semantics.
- Every regime observation must be knowable at its decision timestamp. A feature
  made from completed close `t` may affect only a later causally valid decision or
  fill; no same-bar fill is permitted.
- Preserve `available_at`, `snapshot_id`, `hard_valid`, bounded authorization, and
  current-universe prohibitions. Unknown required lineage fails closed.
- Years are for attribution, stability, and OOS evaluation only; never map years to
  parameters.
- Perform attribution before strategy design. Do not reverse-engineer regimes from
  full-sample best outcomes or optimize narrow thresholds.
- Prefer continuous relationships, coarse economically meaningful bins, quantiles,
  monotonicity, sensitivity plateaus, and simple rules.
- Do not silently replace unavailable breadth, style, industry, or liquidity inputs.
- Preserve failed and negative results. Do not force a V1-R conclusion.
- Do not rerun or overwrite frozen formal replays merely to recreate already
  hash-bound raw ledgers. Reproduction begins with artifact/hash/metric validation;
  any new replay requires its own authorization and preregistration.

