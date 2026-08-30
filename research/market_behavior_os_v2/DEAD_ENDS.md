# Dead ends and preserved negatives

| Item | Disposition | Reuse rule |
|---|---|---|
| MKT-TRND-001 fixed quality efficiency 40/60/80 | REPRESENTATION_NOT_FROZEN: low neighboring stability and coverage | Do not tune the exact window; require structurally different quality representation under fresh spec |
| MKT-TRND-001 same-side age MA40/60/80 | REPRESENTATION_NOT_FROZEN: low neighboring stability and coverage | Do not substitute the best-looking MA horizon |
| MKT-TRND-001 pace transition 10/20/30 versus 60 | REPRESENTATION_NOT_FROZEN: worst neighbor median rho 0.626 | Do not optimize recent/long ratio |
| MKT-TRND-001 strength and alignment | DATA_CONTRACT_LIMITED, not mechanism rejection | Revisit only with independent source or preregistered missingness-compatible design |
| MKT-TRND-001-A PyArrow adapter | INVALID_ENGINEERING | Do not use that reader on the immutable QD-003 files |

Seed-program dead ends remain authoritative in their own ledgers and are not
duplicated here.
