# CHINEXT V1 frontier ranking after residual-return falsification

This ranking was fixed after EXP-PLP-001 rejected post-day-5 incremental
persistence. It allocates information-gain priority; it is not a strategy-feature
ranking and authorizes no modification.

## Closed findings that constrain the choice

- H-004 is frozen for future prospective validation and cannot be optimized.
- Two pre-entry right-tail families, demand/compression and industry-relative
  strength, are rejected.
- Right-tail separation is visible by day 5, but day-5 return has no positive
  association with return earned afterward once shared arithmetic is removed.
- Breadth, pre-entry compression, and industry leadership do not explain severe
  losses under their tested definitions.

## Ranked executable questions

| Rank | Frontier | Information gain and independence | Data / falsifiability | Mining risk and cost | Decision |
|---:|---|---|---|---|---|
| 1 | Full-path excursion ordering | Directly tests whether winner and false-breakout paths differ by the sequence of adversity and opportunity, not another entry feature or landmark return | Existing PIT-valid trade paths contain MFE, MAE, their first-occurrence times, duration, and exit lineage for the frozen 399 cycles | One normalized order statistic plus fixed raw/binary neighbors; low implementation and search cost | SELECT |
| 2 | False-breakout/severe-loss pre-entry formation | Economically important because false breakouts lost 1.81m, but H-011's four transitions show only weak exploratory severe-loss association | Existing trajectory panel is complete | A new feature family would raise search-history risk after the failed four-feature test | DEFER |
| 3 | Execution and portfolio interaction attribution | Could explain realized economics not visible at trade level | Frozen ledgers exist, but invalid Phase 7 descendants cannot be used | Higher implementation cost and lower direct relevance to path formation | DEFER |
| 4 | Cross-sectional dispersion refinement | One earlier exploratory survivor could describe opportunity sets | Daily features exist | Elevated multiple-testing burden after the 93-feature screen; partly redundant with H-004 | DEFER |
| wait | Prospective H-004 validation | Highest confirmatory value | No future untouched sample exists | Cannot execute without future data | WAIT |

## Selected question

Does the ordering of adverse and favorable excursions distinguish extreme winners
from false breakouts beyond excursion magnitude, holding duration, entry state,
year, and exit lineage? The minimum experiment will freeze normalized
`days_to_mfe - days_to_mae` as the primary path-order variable, retain raw-day and
binary MAE-before-MFE views only as neighbors, and will not test an entry or exit
rule.
