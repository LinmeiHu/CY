# V5 Capital-Constrained Portfolio Methodology and Outcome-Blind Freeze

This document freezes V5 before any full-history portfolio NAV is calculated. V5 imports the
authoritative V2 carrier/event builder and V3 continuous-score builder without modifying
either. It does not search for a signal, holding period, score, sizing slope, or cost level.

## Frozen carrier, event stream, and score

- Carrier: exact V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%` at t0.
- Event: first carrier observation after no carrier observation in the prior 20 security
  trading rows.
- Cohort: exact valid V3/V4 event stream after the inherited clean-path rules and the 186
  zero-range t0 feature exclusions.
- Signal time: t0 close. Entry is the inherited next listed legal open; no t0 fill is allowed.
- Continuous score: the unchanged V3 equal average of same-date close-location-danger,
  current-day-loss-danger, five-session-negative-day-persistence, and adverse-gap-danger
  `percent_rank` components. Every input ends by t0 close. Higher is more dangerous.

V3 score construction still uses all contemporaneous valid deep-carrier observations before
event and outcome filtering. Future trigger, return, MFE, MAE, event membership, and future
score distributions never enter a t0 score.

## Frozen executable 20-session horizon

V1-V4 Ret20 enters at t0+1 legal open and values the lot at t0+20 adjusted close. That close
is a valid research endpoint, but CY-006's certified limit-block controls are open-specific.
V5 therefore makes one outcome-blind executable translation: enter at t0+1 open, remain
invested through 20 completed holding sessions (t0+1 through t0+20), and schedule sale for
t0+21 open. If that open is not legally sellable, carry the lot to the first later legal open.
The implementation scans the next 60 security sessions and fails closed if no legal exit is
found; this is an execution-coverage bound, not an alternative holding rule.

The corporate-action-safe adjusted open is `adjusted_close * open / close`, algebraically
equal on entry day to `adjusted_close_t0 * open_t0+1 / preclose_t0+1`. Lots hold normalized
adjusted units rather than naive raw-share continuity. Daily close marks use the inherited
causal close/preclose total-return chain. V5 must bridge every executed Equal-size lot's gross
open-to-open return to its inherited V4 next-open-to-t0+20-close Ret20 before interpreting NAV.

## Frozen causal score-to-size deployment

For a signal date t, the historical reference contains only valid V3 event scores whose
signal dates are strictly earlier than t. Every same-date event is evaluated against the same
pre-date sorted distribution, and the date's scores are inserted only after all assignments
for that date are complete.

When at least 250 prior event scores exist, causal percentile is the empirical CDF
`count(prior_score <= current_score) / prior_event_count`. Ordinary boundaries assign
percentiles `<=20%`, `<=40%`, `<=60%`, `<=80%`, and `>80%` to Q1-Q5. Before 250 prior events,
the event receives neutral Q3 and raw relative weight 1.0. This warm-up convention is fixed
and is not tuned.

The exact V4 primary raw map is:

| Causal bucket | Q1 safest | Q2 | Q3 | Q4 | Q5 riskiest |
|---:|---:|---:|---:|---:|---:|
| Raw relative weight | 1.250 | 1.125 | 1.000 | 0.875 | 0.750 |

The map is positive and monotone; it contains no veto, short, or leverage. V4's pooled
cohort normalizer is not reused as a threshold. On each entry date raw weights are normalized
only across that date's executable signals, so Risk-Aware and Equal receive the same total
new-entry tranche before their own cash constraints. A one-signal day is identical.

## Frozen portfolio and capital rules

There are exactly two policies: `EQUAL_SIZE` and `RISK_AWARE_SIZE`. Each starts with NAV and
cash 1.0, earns zero cash interest, and cannot borrow, short, or lever. Every trading day has
an independent gross-new-notional ceiling of 5% of opening pre-entry NAV. Unused budget stays
cash and is not carried forward. Actual notional is limited by cash after same-open exits; if
buy costs would make cash negative, all same-day entries are scaled proportionally.

All same-day valid signals compete for that one tranche. Equal splits it evenly. Risk-Aware
uses the causal raw weights normalized to the same total. If a security is already open, its
new event is skipped rather than pyramided and is counted. There is no top-k selection,
minimum order, integer-lot rounding, capacity model, position cap, stop, take-profit, or
dynamic exit. Normalized adjusted units permit exact proportional accounting at NAV 1.0.

## Deterministic daily chronology

For each market session:

1. carry prior cash and mark every open lot at the current adjusted open;
2. record opening pre-entry NAV;
3. execute legal scheduled exits at that open, deduct sell costs, and update cash;
4. identify that open's executable new signals and remove already-open securities;
5. set gross new-notional budget to `min(5% * opening NAV, available cash)`, then
   proportionally scale for buy costs if required;
6. allocate the resulting notional under the policy, enter at adjusted open, deduct buy costs,
   and create distinct lots;
7. mark surviving and new lots at current adjusted close; and
8. record close cash, market value, NAV, exposure, concentration, and concurrent lots.

Exit proceeds are therefore available to same-open entries. Close prices never fund that
morning. On a missing/non-trading close, the last causal mark is carried; the inherited V3
clean 25-session path is expected to make this exceptional for held lots.

## Frozen costs and stress

Repository research configuration already freezes 3 bps proportional commission and 5 bps
slippage on each side. V5 uses those values and historical A-share sell stamp duty:

- buy: 3 bps commission + 5 bps slippage = 8 bps;
- sell before 2023-08-28: 3 + 10 stamp + 5 slippage = 18 bps; and
- sell on/after 2023-08-28: 3 + 5 stamp + 5 slippage = 13 bps.

There is no broker-specific RMB 5 minimum because capital is normalized. Slippage is a
proportional cash cost rather than a fabricated order-book fill. The one stress doubles only
commission and slippage: buy 16 bps; sell 26 bps before 2023-08-28 and 21 bps afterward.
Stamp duty is unchanged. Gross portfolios use identical mechanics with zero costs.

## Interpretation boundary

V5 is a daily finite-capital realization of frozen research. It may diagnose clustering,
idle cash, concentration, cost drag, and executable endpoint translation. It may not tune a
signal, percentile boundary, warm-up, weight, tranche, holding period, or cost assumption in
response to portfolio outcomes. No market-impact or capacity claim is made.
