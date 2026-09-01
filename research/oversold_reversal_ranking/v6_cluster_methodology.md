# A-Share Deep-Oversold Portfolio V6 Methodology

## Scope and frozen hypothesis

V6 is a single, outcome-blind capital-translation test. It asks whether the number of
simultaneous frozen deep-oversold signals identifies dates that deserve more total new-entry
capital. It does not search for stock-level alpha, change the carrier, or tune a portfolio
parameter.

The authoritative V5 Equal Size GROSS portfolio is the control. V6 changes only the total
desired budget on an active entry date. Within-date allocation is equal weight; the V3/V4
stock-level risk score is economically inactive.

## Frozen upstream contract

V6 imports V5's exact event and execution tables:

- exact V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%`;
- first deep-carrier observation after no deep-carrier observation in the prior 20 security
  trading rows;
- t0 close signal and inherited next listed legal-open entry;
- corporate-action-safe adjusted open `adjusted_close * open / close`;
- normalized adjusted units and adjusted-close daily marks;
- positions held through t0+20 and sold at the first legal open on or after t0+21;
- long-only, finite cash, no leverage, no borrowing, and no forced liquidation; and
- V5's deterministic open-exit, cash-update, open-entry, close-mark chronology.

No V1-V5 artifact is modified. Primary analysis is gross of transaction costs.

## Causal cluster count

For entry date `t`, `N_t` is the number of frozen qualifying events scheduled to enter on that
date. Each constituent event was formed no later than its t0 close, strictly before its legal
entry open, so the complete same-entry-date count is available before allocation. No forward
return, later price, exit state, or V3 risk score enters the budget.

The causal reference is:

`M_t = median(N_s for prior active entry dates s < t)`.

Only strictly prior active dates are admitted. Zero-signal dates are excluded. The current
date's `N_t` is appended to history only after its budget has been assigned. Until 60 prior
active dates exist, the rule is neutral and uses the V5 5% desired budget; 60 is frozen and is
not optimized.

## Preregistered treatment

Let opening NAV be V5's current pre-entry NAV, measured at the open before same-open exits.
After legal exits, available cash funds entries. On an active date:

- warm-up: `desired_t = 0.05 * opening_NAV_t`;
- afterward: `desired_t = 0.05 * opening_NAV_t * (N_t / M_t)`;
- `actual_t = min(desired_t, available_cash_t)`; and
- every executable event receives `actual_t / N_t` when all frozen events are executable.

There is no count threshold, floor, ceiling other than finite cash, leverage, tranche
roll-forward, fitted multiplier, or alternate rule. Unused cash remains cash. Execution data
fail closed exactly as in V5.

## Frozen diagnostics

V6 reports the full active-date count distribution and fixed descriptive regimes `1`, `2-5`,
`6-10`, `11-20`, and `>20`. These regimes never alter allocation.

The count-to-outcome bridge uses the V5 executable gross trade return at the legal exit open.
For each entry date, it computes the equal-event-weight basket mean and supporting mean V4
MAE20. Spearman correlation of `N_t` with basket return is primary; Pearson is secondary.
Five descriptive count-rank groups split active dates sorted by `(N_t, date)` into approximately
equal numbers. This tie-breaking is descriptive only and cannot affect the causal portfolio.

The event-contribution bridge sums gross trade returns by entry date and separately sums the
positive part of event returns. "Highest count" means the descriptive fifth count-rank group,
fixed by count and date alone. Portfolio P&L attribution uses realized gross P&L, not independent
trade averages.

Broad stability blocks remain `2018-2020`, `2021-2023`, and `2024-2026`.

## Decision rule

The verdict is selected only after the one frozen broad run:

- `CLUSTER_CAPITAL_TRANSLATION_SURVIVES` requires a credible, broadly persistent positive
  count-to-basket relationship and a meaningful gross NAV or risk-adjusted improvement;
- `CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS` requires a genuine cluster signal but
  no meaningful portfolio translation;
- `CLUSTER_HYPOTHESIS_FAILS` applies when count does not credibly identify better baskets and
  portfolio economics do not improve; and
- `INCONCLUSIVE` is reserved for implementation, execution, or data limitations.

Weak results are not a reason to alter the frozen rule or declare the study inconclusive.
