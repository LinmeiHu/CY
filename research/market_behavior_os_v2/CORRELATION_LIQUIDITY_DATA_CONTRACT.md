# Strategy-independent correlation/liquidity data contract

## Registered source and PIT boundary

MKT-CLQ-001 uses the same exact CY-006 manifest and the same 2018-2023 partition
hashes frozen in `BREADTH_DATA_CONTRACT.md`. The source contains 6,155,390 rows
from 2018-01-02 through 2023-12-29. The runtime must reverify the registry,
manifest, partitions, duplicate-key audit, and `available_at <= decision_at`
gate. The PIT grade remains bounded PIT-B.

The representation timestamp is the completed official close at 15:00
Asia/Shanghai. There is no signal or action; the first possible action would be
a later causally valid session.

## Price and population contract

Security return steps use the exact action-aware continuous coordinate in
`BREADTH_DATA_CONTRACT.md`. Unsupported rights participation, unavailable action
facts, blocking actions, nonpositive rebased prices, invalid OHLC, calendar
gaps, or unknown required lineage fail closed. No future adjustment factor is
used.

The primary population is the same 120-consecutive-session, current-trading,
strategy-independent market core. ST securities remain in `ALL_STATUS`; `NON_ST`
is a sensitivity denominator. There is no CHINEXT V1 membership, liquidity
threshold, listing-age filter, signal, current-survivor list, or outcome-based
selection.

## Liquidity-unit audit

Before construction, every eligible current row must have:

- finite positive `amount`;
- finite nonnegative `turnover_fraction` and `turnover_pct`;
- `abs(turnover_fraction - turnover_pct / 100) <= 1e-12`.
- `amount == round(amount, 3)` so exact `DECIMAL(38,3)` ledger arithmetic
  preserves the registered source value without rounding.

Observed on the frozen 2018-2023 eligible rows before MKT-CLQ-001: 5,814,399 of
5,814,399 rows have positive amount and finite nonnegative turnover, and the
maximum unit difference is `1.1102230246251565e-16`. This readiness result is an
input audit, not representation or usefulness evidence.

Binary floating sums are not accepted for conservation. Exact amount totals and
disjoint concentration partitions use `DECIMAL(38,3)` after the scale audit.

Own-amount reference windows contain exact prior exchange sessions and exclude
the current observation. A missing, invalid, or nonconsecutive required row
invalidates the ratio; it is not imputed, clipped, normalized, or substituted.
Liquidity concentration must conserve current amount exactly across its
constituent securities.

## Forbidden inputs and fail-closed conditions

Forbidden inputs are CHINEXT V1 or any strategy membership; signals, entries,
trades, fills, P&L, MFE, MAE, exits, durations, or outcome classes; future
returns; post-decision observations; current constituent lists or survivors;
unregistered market-cap, float, fund-flow, sentiment, participant identity, or
industry fallback; CY-011; and CY-006 partitions after 2023.

Construction fails closed on identity/hash mismatch, time travel, duplicate
keys, liquidity-unit mismatch, amount nonconservation, insufficient view size,
insufficient exact-window coverage, or noncausal historical normalization.
