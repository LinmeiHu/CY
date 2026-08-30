# EXP-OBL-011 structured evidence

## Scientific decision

`REJECTED` under the frozen contract. Continuous same-session selection pressure
has positive raw association, but neither co-primary endpoint reaches its fixed
controlled-magnitude gate after binary contested selection, absolute RS, breadth,
V1/market state, liquidity/risk, and year are held fixed.

This was a post-secondary follow-up: `selection_pressure` had already been seen
as a preregistered non-rescuing secondary in EXP-OBL-010. It is not independent
confirmation.

## Co-primary evidence

| Endpoint | Raw rho | Raw LOYO | BH q | Controlled rho | Controlled LOYO | Gate |
|---|---:|---:|---:|---:|---:|---|
| MFE | 0.231504 | 8/8 | 0.000006 | 0.076590 | 8/8 | FAIL: below 0.08 |
| non-false-breakout | 0.125613 | 8/8 | 0.012032 | 0.038008 | 8/8 | FAIL: below 0.08 |

All three raw temporal-block signs are positive, but the 2022-2023 values are
only 0.011828 for MFE and 0.009970 for non-false-breakout. The extended and
development values are 0.162032/0.345481 for MFE and 0.076405/0.288825 for
non-false-breakout.

## Falsification

- Removing 2025 leaves raw rhos 0.178645 and 0.083194.
- Removing the top 1% absolute-PnL cycles leaves 0.225685 and 0.119999.
- Removing extreme winners leaves 0.204880 and 0.101049.
- Removing severe losses leaves 0.254375 and 0.148417.
- Post-2021 rhos are 0.279503 and 0.193754.
- After separately controlling candidate count and vacancies, partial rhos fall
  to 0.023650 and 0.055138.
- After holding-duration and exit-reason controls, partial rhos are 0.105972 and
  0.033651.
- Every leave-one-security and leave-one-industry raw estimate remains positive.

Thus the raw association is not a few-security or extreme-tail artifact. It is
nevertheless insufficiently incremental and nearly null in the 2022-2023 block.
The prespecified controlled gate, not post-hoc interpretation, determines the
rejection.

## Integrity and boundaries

- Population: 399 events; 383 controlled complete cases.
- Frozen lineage: `LINEAGE-OBL-009-2BECCEFAF46C1140`.
- Output table SHA-256:
  `2cc206f1d29a7a9168a38ccd5a6b01622a8ff061fc489f355ba7eb3fdecd4d68`.
- Result SHA-256:
  `972883826e13da5981c649456a4d13dcfb5042baca738853453fe2047efbf946`.
- Generated report SHA-256:
  `20891722c152afef4eea19e0969f3a6b60798da29fb0b4fb0d652414385c6151`.
- Generated evidence packet SHA-256:
  `48a7cca1588bf35849132ba86b514a0f3c2d58a57a0553b33905a1956d138b4d`.
- Two complete executions produced byte-identical outputs.

No pressure threshold, rank/margin variant, filter, entry, exit, sizing, overlay,
canonical V1 change, candidate rule, or CY-011 access is authorized.
