# Dead ends and preserved negatives

| Item | Disposition | Reuse rule |
|---|---|---|
| MKT-TRND-001 fixed quality efficiency 40/60/80 | REPRESENTATION_NOT_FROZEN: low neighboring stability and coverage | Do not tune the exact window; require structurally different quality representation under fresh spec |
| MKT-TRND-001 same-side age MA40/60/80 | REPRESENTATION_NOT_FROZEN: low neighboring stability and coverage | Do not substitute the best-looking MA horizon |
| MKT-TRND-001 pace transition 10/20/30 versus 60 | REPRESENTATION_NOT_FROZEN: worst neighbor median rho 0.626 | Do not optimize recent/long ratio |
| MKT-TRND-001 strength and alignment | DATA_CONTRACT_LIMITED, not mechanism rejection | Revisit only with independent source or preregistered missingness-compatible design |
| MKT-TRND-001-A PyArrow adapter | INVALID_ENGINEERING | Do not use that reader on the immutable QD-003 files |
| MKT-BRTH-001 parallel construction | INVALID_NONDETERMINISTIC | Never cite its role results; use exact serial MKT-BRTH-002 only |
| MA20 participation with MA10/MA60 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.668 | Do not choose the better MA10 neighbor or tune horizon |
| Median MA20 depth with MA10/MA60 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.679 | Require structurally different depth representation under fresh spec |
| 5-session breadth momentum with 3/10 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.608 | Do not optimize return horizon |
| 5-session participation acceleration with 3/10 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.044 | Exact second-difference family is highly horizon-specific |
| MA20 industry diffusion with MA10/MA60 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.664 | Broader diffusion family remains open |
| Stock-versus-industry participation divergence | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.504 | Do not tune MA horizon or industry threshold |
| MA20 net crossing over 5 sessions with 3/10 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.641 | Momentum/crossing cluster remains open under different semantics |
| 5-session change in median 20-session-relative amount with 3/10 neighbors | REPRESENTATION_NOT_FROZEN: worst median neighbor rho 0.534 | Do not tune the change horizon; broader liquidity transition family remains open |
| MKT-CLQ-001-A ambiguous exact-window join | INVALID_ENGINEERING | Qualified joins preserve the unchanged scientific design |
| MKT-CLQ-001-B binary amount conservation | INVALID_ENGINEERING | Never relax conservation; exact DECIMAL ledger is allowed only after the registered three-decimal scale audit |
| 5-session concentration decay across top5/10/20 and 3/5/10 horizons | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.683 | Do not tune threshold or horizon; level concentration remains valid |
| 5-session discovery deterioration across 40/60/80 and 3/5/10 horizons | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.500 | No joint leader-failure geometry; broader family remains open |
| Volatility term structure RV10/RV40 with adjacent ratios | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.634 | Do not optimize the short/long pair |
| Five-session downside squared-return-mass share with 3/10 neighbors | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.694 | Do not tune smoothing horizon; broader asymmetry family remains open |
| Market minute selloff-duration level using p40/median/p60 cross-section | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.545 | Do not choose a favorable quantile; broader duration family remains open |
| Market auction-to-continuous-open level using p40/median/p60 cross-section | REPRESENTATION_NOT_FROZEN: worst neighbor rho 0.474 | Do not choose a favorable quantile; auction state remains underexplored |
| Five-day OLS slopes for all 34 market minute descriptors | REPRESENTATION_NOT_FROZEN: fixed endpoint/last-three-session worst correlations 0.288-0.514 | Do not select the best horizon or descriptor; require a structurally different non-slope trajectory hypothesis |

Seed-program dead ends remain authoritative in their own ledgers and are not
duplicated here.
