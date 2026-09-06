# State

## Current phase

Complete — final synthesis and terminal decision D.

## Status

Complete.

## Completed

- Created an independent `opportunity_conversion` research surface.
- Inherited the authoritative V1 strategy hash and prior regime-attribution
  report hashes.
- Froze Outcome C and the rejected A40 exposure overlay as prior evidence.
- Froze conversion metrics, mutually exclusive terminal classes, path
  descriptors, oracle boundaries, robustness rules, and the strategy gate.
- Identified the primary 399-cycle ledger and existing causal entry features.
- Completed OC-EXP-P0-001: all frozen source and strategy hashes match.
- Completed OC-EXP-P1-001: reconstructed 399/399 completed cycles and 5,551
  eligible holding-path rows with zero cycle loss.
- Reconciled entry/exit lineage, capital, P&L, return, MFE, MAE, timing,
  giveback, early returns, and nine causal stock features at 1e-12 tolerance.
- Frozen population counts: 84 opportunity20, 32 opportunity50, 213 false
  breakouts, and 44 severe losses. Coverage subsets will remain explicit.
- Two targeted metric-boundary/path tests pass.
- OC-EXP-P2-001 passed: 1,942 daily sessions reconcile to 1,145 candidate
  evaluation sessions, 1,821 final candidate events, and 409 selected entries
  including ten terminal-open cycles. Breadth relates positively to candidate
  count/rate, but only 5/8 yearly signs agree; selected-trade opportunity20 is
  positive in 7/7 estimable years and 8/8 LOYO, while terminal return is mixed.
- Within-year breadth quintiles show an opportunity plateau: opportunity20 is
  about 10% in Q1-Q2 and 27-29% in Q3-Q5, while terminal median is negative in
  all five quintiles. MFE p90 is not monotone and peaks in Q3.
- OC-EXP-P3-001 passed as an attribution experiment: zero of 54 causal
  entry-feature/outcome pairs passes the frozen effect, yearly, LOYO, and BH
  gates before extreme sensitivity.
- OC-EXP-P4-001 passed: 52 MFE20-50 cycles retain median 33.6% capture and only
  17.3% convert to terminal >=20%; 32 MFE>=50 cycles retain median 58.4% and
  93.8% convert. Early peaks leave more time for giveback; time-to-MFE fraction
  is positively, not negatively, related to capture. This locates holding-path
  leakage but remains hindsight information.
- OC-EXP-P5-001 passed. Opportunity20 trades contribute +2.981m realized P&L;
  the other 315 completed trades contribute about -1.549m. False breakouts
  contribute -1.809m; 42/44 severe losses overlap that class.
- Of 45 opportunity20 nonconversions, 39 still end positive and contribute
  +0.494m; only six end nonpositive. MFE>=50 converts to terminal >=20% in
  30/32 cases, but only 15/32 retain >=50%.
- Opportunity20 peak-close giveback has a 2.243m initial-capital oracle ceiling,
  larger than the 1.809m false-breakout ceiling, but the ceilings are
  overlapping, non-NAV, and the exit ceiling is hindsight-only.
- Strict post-exit coverage is 399/399 at 5 and 10 sessions and 398/399 at 20.
  Opportunity20 nonconversions have +6.25% median close return after 20
  sessions, but the maximum-high diagnostic is an oracle.
- Frozen executable exit counterfactuals contradict a stable improvement:
  disabling individual or market exits reduces 2024-2025 total return by
  10.56pp and 13.52pp; development winner-hold gains 9.51pp but loses 1.91pp
  in 2022-2023 OOS with only two activations.
- OC-EXP-P2-002 passed on 1,821 final candidate events with 1,812 strict
  fixed-20-session outcomes. Selected candidates modestly exceed unselected
  candidates (Opp20 25.9% vs 23.3%; close20>=20% 13.7% vs 10.2%). On 30
  genuinely competitive selection days, selected candidates have +3.19%
  within-day centered MFE20 versus -1.02% for unselected; V1 is not shown to
  select systematically worse candidates.
- Only 30/259 selection days have an executable covered alternative. On those
  days, the hindsight best candidate is captured 43.3% of the time and a top-3
  candidate 70.0%; median MFE20 regret is 3.07%. The scope is narrow and the
  diagnostic is not an alternate-entry replay.
- OC-EXP-P6-001 passed: breadth robustly coincides with cross-sectional
  return20 standard deviation (rho 0.264), p90-p10 spread (0.308), and market
  right-tail frequency (0.756), all 8/8 yearly and LOYO. Zero of 27 continuous
  Breadth x stock-feature interactions passes the full gate.
- OC-EXP-P7-001 passed as an audit. Breadth->MFE and opportunity are positive
  in all 13 rolling windows and stable under top-MFE removal; breadth->terminal
  is mixed and flips slightly negative after removing 20 largest-P&L trades.
  Zero of 135 neighboring-definition entry-feature tests passes. The formal
  strategy-design gate fails.
- OC-EXP-P8-001 passed. `FINAL_REPORT.md` selects Decision D and stops without
  a minimum candidate.
- Final targeted validation: 7/7 tests pass.
- All five artifact-generating scripts were rerun consecutively; artifact and
  report hashes were byte-identical before and after the rerun.

## In progress

None.

## Next

No automatic phase remains. Any new strategy research requires a separately
frozen future decision-time mechanism and evaluation period.

## Hard blockers

None. The absence of untouched OOS for a new rule is an epistemic boundary,
not a blocker to the explanatory conclusion.
