# EXP-ECC-001 evidence packet — same-day entry-cohort crowding

## Decision

`REJECT` H-018. Larger same-day accepted-entry cohorts do not increase
false-breakout incidence or the H-016 opportunity-before-adversity topology.
The observed associations are weakly opposite the preregistered direction and
all five frozen gates fail.

## Frozen question and mechanism

H-018 asked whether simultaneous accepted breakout entries dilute marginal
selection quality or concentrate crowded failures beyond breadth and fixed entry
state. It predicted positive continuous association between all-entry cohort size
and completed-trade false-breakout rate at the independent cohort-date level.

This was attribution only. No threshold, throttle, sizing rule, replay, ranking
change, entry change, or production change was tested.

## Data and PIT integrity

- Exact accepted entry fills: 409 across three hash-bound execution ledgers.
- Completed-cycle endpoints: 399, occupying 255 independent execution dates.
- Multi-entry dates: 92.
- Cohort sizes: 163 dates of size 1, 64 of size 2, 16 of size 3, 6 of size 4,
  3 of size 5, and one each of sizes 6, 7, and 8.
- Primary unit: one unweighted cohort date. Trades within a date were not treated
  as independent primary observations.
- Every admitted date has exact equality between all accepted fills and completed
  cycle entries. The ten terminal open development entries receive no invented
  endpoint.
- Frozen seven-input-plus-spec aggregate: `7d2b366b...`.
- Preexisting 230-file aggregate before and after both executions:
  `39200702b073574d0953b452a4b13aacfc688647c1ec75c0827b5ddcdefeb623`.
- Two full executions are byte-identical.

## Primary evidence

| Test | Estimate | Temporal direction | Gate |
|---|---:|---:|---:|
| Cohort-date raw | rho -0.045 | 0/8 positive LOYO | fail |
| Within-year ranked | rho -0.056 | — | fail |
| Fixed controlled | partial rho -0.118 | 0/8 positive LOYO | fail |
| Trade-level neighbor | rho -0.059 | 0/8 positive LOYO | fail |
| H-016 topology | rho -0.042 | 0/8 positive LOYO | fail |
| Cohort size below 5 | rho -0.032 | 0/8 positive LOYO | fail |

The multi-entry-minus-single-entry false-breakout-rate difference is -0.0143.
Block rhos are -0.124 for 2018-2021, -0.023 for 2022-2023, and +0.075 for
2024-2025; the required positive direction does not replicate across blocks.

## Falsification and interpretation

The result is not a breadth-redundancy downgrade of a positive raw relationship:
the raw, controlled, trade-level, topology, small-cohort, and two of three block
estimates already oppose the hypothesized direction. The negative controlled
estimate is not promoted into an inverse rule because no inverse mechanism was
preregistered and the pooled p-value is 0.067.

The narrative hypothesis/registry named leave-security and leave-industry attacks,
but the exact frozen spec and hash-bound runner did not serialize those views.
This is a recorded non-decisive protocol omission. It cannot rescue H-018 because
the primary raw and controlled gates fail before concentration evidence is
considered. The runner is not repaired or rebound after execution.

## Scientific boundary

Accepted-entry cohort count is not supported as an explanation of false-breakout
formation and provides no basis for entry throttling or portfolio sizing. The
completed-path H-016 topology remains supported, while its cause remains
unexplained by T+1 gap or simultaneous-entry crowding.

## Output identities

- cohort table SHA-256: `a12e988d54b3be28bf9a8bf312a209eed4c42a91061a9924160478752ec21641`;
- result JSON SHA-256: `a9af99e63d7b4ba49a03aba71d5ed8bc6708612bb5db1a3ada3fe91978787d1e`;
- generated report SHA-256: `20072f8943d488c9c5689d3753529f3237a207159db651a8c4f59e67e1db7af4`.
