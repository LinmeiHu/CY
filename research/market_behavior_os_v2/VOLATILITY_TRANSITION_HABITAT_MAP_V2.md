# Continuous volatility transition and habitat map V2

MKT-VOL-TRANS-002 is a coverage-correct retry of the scientific design frozen
in `VOLATILITY_TRANSITION_HABITAT_MAP.md` and MKT-VOL-TRANS-001 spec
`21145136...`.

MKT-VOL-TRANS-001 passed all immutable input, key, timestamp, population, and
response-shift audits. It then stopped before an output artifact was accepted
when one block-A direction-habitat PIT cell retained only 123 complete
observations against the unchanged 150 minimum. The shortfall arises because
the causal volatility PIT warm-up and an index's lower direction-PIT half do not
guarantee 150 observations within every separate view/denominator cell.

No result is accepted from 001. The 150-observation gate is not lowered, the
50/50 or 40/60 habitat definitions are not changed, and no index, view,
denominator, coordinate, block, or control is removed.

The only estimator correction is for the direction modifier:

- within each index and denominator, stack all four governed volatility views
  before estimating the low- and high-direction partial correlations;
- compute high minus low for both denominators;
- take their median as that index's modifier effect;
- summarize across all six indices and retain the unchanged four-of-six sign
  gate.

Each governed view contributes exactly one row per date and all four are
retained with equal frequency. This is an all-view, cross-index modifier
estimand, not favorable-view pooling. The discovery modifier remains estimated
in each of the eight matching view/denominator groups because its PIT habitat is
itself view-specific and its cells satisfy the frozen support architecture.

The retry performs a complete baseline, phase, direction-modifier, and
discovery-modifier support audit for every block/split/coordinate before any
correlation is estimated. All scientific fields remain unchanged: t+25
response, controls, causal PIT habitats, raw/PIT/relative coordinates, blocks,
effect/sign/magnitude gates, contamination label, no-rescue rule, prohibited
fields, and claim boundary. This correction is frozen before any 002 estimate.
