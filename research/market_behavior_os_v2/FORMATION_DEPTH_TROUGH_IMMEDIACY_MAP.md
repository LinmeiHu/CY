# Formation-depth trough-immediacy map

Frozen after MKT-FORMDEPTH-PATH-001 and before estimating any association between
formation depth and future trough offset. The question is whether deeper
formation shifts the earliest adverse trough toward the first future session or
delays it within the fixed response path.

## Exact response

Reuse the bound PATH-DATA-001 earliest-exact-minimum-low selection with earliest
tie resolution. Within the exact combined `cross20` response arm define:

- primary `FIRST_SESSION_TROUGH_SHARE_H3` as count with h=3 trough offset 1
  divided by exact crossing response count;
- sole neighbor `FIRST_SESSION_TROUGH_SHARE_H5` identically within h=5.

Accepted and rejected closing arms use the same response as robustness views.
Exact equality remains count-only. Do not test offset 2/3/4/5 separately, mean
offset, a best cutoff, a different trough tie, or another horizon. Those are
deterministically related or would create post-result selection.

These shares are future-response attribution. They are unavailable at t, may not
be used as predictors, and do not describe an executable stop or entry time.

## Fixed association design

Use the unchanged market formation-depth PIT coordinate, 6,627-row complete
domain, five controls, eight view/denominator cells, 2020--2023 supported years,
leave-one-year-out checks, 2018--2020/2021--2023 blocks, and nonoverlap phases.
The joint predictor clock remains 15:30 and future response begins t+1.

Direction is two-sided and frozen before estimates. The primary passes only if:

- median h=3 absolute PIT partial rho >=0.10;
- at least six of eight cells share the nonzero median direction;
- both block medians share that direction and absolute rho >=0.05;
- every supported-year and leave-one-year-out median shares that direction;
- the h=5 median shares that direction and absolute rho >=0.05;
- at least two of three h=3 and four of five h=5 phase medians share it;
- controlled high-minus-low PIT-tail share gap shares it and has absolute
  magnitude >=0.02;
- accepted and rejected h=3 median partial rhos share it.

Positive direction classifies `EARLIER_TROUGH_WITH_FORMATION_DEPTH`; negative
direction classifies `LATER_TROUGH_WITH_FORMATION_DEPTH`. Failure of any gate is
`NO_STABLE_TROUGH_IMMEDIACY_SHIFT`.

Passing would establish a stable market-date timing association under this exact
future-response definition. It would not establish causality, prediction,
imminent acceleration at t, a trading clock, execution, habitat, payoff, or a
strategy rule. V1, post-2023 data, strategy outcomes, and CY-011 remain closed.
