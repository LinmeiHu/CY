# Circulating-size external market-engine geometry map V2

Frozen before MKT-STYLE-GEO-002 estimates any cross-family correlation or joint
reconstruction. It inherits the exact scientific design and input identities of
MKT-STYLE-GEO-001. The only correction is the estimand for the governed-view
relative-rank coordinate.

## Why MKT-STYLE-GEO-001 is invalid

`relative_view_rank_pct` is a contemporaneous ordinal comparison across the
four governed market views on one date and denominator. MKT-STYLE-GEO-001
incorrectly required it to vary through time inside each fixed view. The first
failed cell was size structure, ALL_A, ALL_STATUS, 2021: the size rank was
always 0.75, turnover rank always 0.50, and volatility rank always 0.50 even
though each field varied across the four views on every date.

The frozen nondegeneracy gate therefore stopped the experiment before any
correlation, reconstruction, panel, result, or report. This is an estimand
mismatch, not a failed size role and not evidence about external distinctness.

## Unchanged geometry

The six accepted size roles, their exact three-control sets, all six bound input
panel/result hashes, 2021--2023 eligibility, exact 15:00 availability, and raw,
causal-PIT, relative-to-ALL_A, and relative-rank source values are unchanged.
Raw, PIT, and relative-to-ALL_A keep their original within-view time-series
estimators and support audits.

The pairwise absolute-rho threshold remains 0.85. Joint adjusted rank R2 must
remain below 0.70 median and 0.85 maximum. Every coordinate is conjunctive; no
role, control, date, view, denominator, coordinate, year, regression subset,
threshold, or failed representation may be selected or deleted to rescue a
result.

## Correct relative-rank support unit

For each role, denominator, and eligible year, construct a matched date cell
only when all four governed views have finite values for the role and all three
fixed controls. Require at least 150 such dates. On at least 150 dates, every
one of the four fields must also have at least two distinct values across views.
Complete this audit for every role before estimating any geometry.

## Correct relative-rank estimators

For pairwise geometry, calculate Spearman correlation across the four views on
each complete date. Within each denominator-year cell, summarize the median
absolute daily cross-view correlation. Apply the unchanged 0.85 gate to the
median of the six denominator-year summaries.

For joint reconstruction, pool the four-view ranks within each denominator-year
cell and remove date fixed effects by demeaning the target and all three
controls within date. Regress the demeaned target on the demeaned controls with
no intercept. With `n` pooled observations, `g` dates, and `p=3` controls, use
adjusted within R2

`1 - (1 - within_R2) * (n - g) / (n - g - p)`.

Apply the unchanged 0.70 median and 0.85 maximum gates across the six
denominator-year cells.

## Claim boundary

Passing establishes contemporaneous external distinctness only. It does not
establish causality, a small-cap premium, risk appetite, temporal dynamics,
future return, strategy habitat, timing, execution, capacity, or a rule. No
Trend x Breadth x Style interaction is authorized. Future fields, strategy
outcomes, failed roles, post-2023 data, and CY-011 are prohibited.
