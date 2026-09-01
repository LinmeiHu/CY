# A-share ultra-short discovery cycle 014

## ENVIRONMENT

Repository: `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830`; branch: `research/ashare-ultrashort-v1`; starting checkpoint: `cedbb7bbf1`.

## DATA

CY-006/CY-008 contain 6,155,390/6,114,413 governed rows with zero lineage or time-travel failures. The shared causal domain has 2,928,177 eligible security-dates. The raw-minute lifecycle read contains 10,490,971 rows for 43,531 preidentified limit-close sessions.

The compact panel contains 79,012 rows, 4,376 securities, 128 PIT industries, and 1,205 dates. Post-2023 and CY-011 were not read.

## GATE_DESIGN_AUDIT

The audit was frozen before outcomes. Hard validity, after-cost break-even, chronology, effective sample/usability, and next-open executability are promotion gates. h1/h3, severe loss, concentration, redundancy, and mechanism geometry are diagnostics. No arbitrary 80% coverage gate exists.

## FROZEN_FAMILY_MAP

| Slot | Family | Deduplication |
|---|---|---|
| A | Price-limit reopen--reseal acceptance | `NEW_DISTINCT` |
| B | Liquidity-shock price assimilation | `NEW_DISTINCT` |
| C | Late-session acceptance/rejection | `NEIGHBOR_OF_PRIOR` |
| D | Event-driven reclaim/failure | `NEIGHBOR_OF_PRIOR` |
| E | Optional independent family | `DEFERRED` |
| Cycle 013 | Industry minute leader--follower | `ALREADY_TESTED`; remains `SIMULTANEOUS_COMOVEMENT_ONLY` |

## SCREEN_RESULTS

| Family | Decision | h2 net | h2 excess | Early excess | Late excess | Severe | Severe vs control |
|---|---|---:|---:|---:|---:|---:|---:|
| price_limit_reopen_reseal_acceptance | NO_SIGNAL | -0.629% | 1.077% | 1.137% | 1.041% | 17.17% | -4.41% |
| liquidity_shock_price_assimilation | NO_SIGNAL | -0.696% | -0.302% | -0.426% | -0.220% | 6.46% | 0.78% |

Price-limit h1/h3 net returns are -0.446%/-0.843%; their excesses remain positive because simple-seal controls are substantially worse. Liquidity-shock h1/h3 net returns are -0.592%/-0.812%, with increasingly adverse excess. These neighbors are diagnostic only.

## PROMOTED_REPLAYS

No family earned replay.

## STOPPED_FAMILIES

Price-limit reopen--reseal acceptance is stopped as `NO_SIGNAL`: it is less bad than simple-seal control, but the selected long leg loses after cost in both blocks. Liquidity-shock assimilation is stopped as `NO_SIGNAL`: selected and relative economics are adverse. Neither may be rescued through thresholds, formulas, h1/h3 selection, top-N, or controls inside this lane.

## PORTFOLIO_RESULTS

No executable portfolio was run because zero families passed the frozen cheap-screen economics. Therefore no family improved a real executable portfolio, and no portfolio metric is inferred from factor-screen elegance.

## RESEARCH_CONCLUSION

`NO NEW ULTRA-SHORT STRATEGY CANDIDATE.` No genuinely new investable 1--3-session edge appeared. The price-limit relative excess and severe-path improvement are mechanism/risk diagnostics only; neither tested family is investable under its frozen long-only translation.

## NEXT_BEST_DIRECTION

The strongest remaining headroom is information unavailable in the current summary-OHLCV lane: governed order-book/queue state or investor-flow identity. The next budget should move to that independent lane under a separate data contract, not deepen either stopped family.

## BOUNDARIES

All evidence uses consumed 2018--2023 development history. Post-2023 and CY-011 were not read. No OOS, validation, live, or production claim is made.

- Spec: `e35ed20d28b599ae279eeab5aad3af5836ce483fdfead3153cf040df2f4d4eb7`
- Gate audit: `c2cba3f5957ad50cf5a242515b90d8172c5c3cfab38e1845e3c3e5584e32286f`
- External panel: `f287a43c3e09d959cb71c43940151f4c16fdf9b1ee5930cfb66f380a620d175d`
- Summary: `a11413b41871539734d54a186b7db2137c8e38ccc56ad1678b3e9fc32c06b4e9`
