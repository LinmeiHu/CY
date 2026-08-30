# PIT data availability audit for original-breakout lineage

## Registered daily and intraday assets

| Asset | Coverage / semantics | Valid use in this program |
|---|---|---|
| CY-006 | 2018-01-01..2026-08-12 daily raw OHLCV/amount, float, turnover, PIT industry, trading/action/rule context, row `available_at`, snapshot, and `hard_valid` | Outcome-blind daily base, RS, volume/turnover, liquidity, industry, and context features after row gates |
| QD-004 | 2000-06-09..2026-08-12 raw/unadjusted 1-minute OHLCV; volume shares, amount CNY; completed local bar timestamps | Event-scoped signal-session paths after exact inventory/session checks; no same-bar action |
| QD-005 | Virtual deterministic session-aware aggregation of QD-004 | Fixed 5-minute neighboring representation only; no independent vendor substitution |
| CY-008 | 2018-01-01..2026-08-12 daily minute aggregates plus six 09:31..10:00 completed five-minute windows, with daily context, snapshots, and hard-valid gates | QD-004 reconciliation and opening-window timing validation |
| UN-001 | Historical depth/order queue and tick-by-tick orders unavailable | None |

## Existing bounded event coverage

The accepted identity artifact contains 399 unique completed cycles from
2018-01-09 through 2025-12-10. Prior outcome-blind infrastructure established
399/399 exact signal sessions, 96,159 QD-004 rows (241 per event), 399 CY-008
daily gates, and 2,394 opening five-minute windows, with exact reconciliation.
This program will rematerialize its own feature artifact rather than importing
the old outcome-bearing result table.

## Timestamp, sessions, and auctions

- Raw QD-004 timestamps represent completed bars in local Shanghai time.
- The expected stored session grid is 09:30 auction plus continuous 09:31..11:30
  and 13:01..15:00, 241 rows total.
- The 09:30 row is auction information and is kept distinct. Continuous-session
  trajectory calculations use 240 bars unless explicitly frozen otherwise.
- Full-session features are conservatively available at 15:30.
- Suspended/incomplete/hard-invalid sessions fail closed. Price-limit-locked flat
  sessions are retained with an explicit neutral mathematical rule.

## Adjustment and units

Intraday prices are raw/unadjusted. Within-session ratios avoid cross-action
coordinates. Cross-session daily formation uses CY-006 corporate-action-aware
history semantics and must validate action visibility. QD-004 volume is shares
and amount is CNY; `sum(amount)/sum(volume)` reconstructs session VWAP.
Intraday turnover additionally needs causal circulating shares from CY-006 and is
not treated as a native minute field.

## Missing data families

No governed historical tick transactions, bid/ask quotes, full depth, queue
priority, cancellations, hidden liquidity, or real participant identities exist.
Claims of “absorption” may use only preregistered limited price-impact/recovery
proxies and cannot become order-flow truth.

## Governance conclusion

Daily and signal-session trajectory research is feasible at bounded PIT-B grade.
Strict archival PIT-A and participant-intent claims are not. No new dataset or
download is needed for the first taxonomy. CY-011 is outside this audit and
remains locked.
