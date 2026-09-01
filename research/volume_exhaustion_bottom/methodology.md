# Methodology

## Data discovery and authority

The authoritative input is registered asset `CY-006`, located at
`/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily`.
It is a nine-partition, frozen PIT-B causal daily table with 9,421,907 rows, 5,682 symbols,
and coverage from 2018-01-02 through 2026-08-12. Its registered audit passes coverage,
duplicate-key, time-travel, consistency, and cross-table gates.

Key physical fields are date, symbol, raw/unadjusted OHLC and preclose, volume in shares,
amount in CNY, turnover as a fraction, historical trading/ST state, price-limit/open-block
state, circulating shares, PIT industry, corporate-action fields, component snapshots,
aggregate `available_at`/`snapshot_id`, and `hard_valid` with explicit reasons. The final
research sample uses only `hard_valid` trading rows. Unknown lineage in the trailing feature
window or outcome path fails closed.

The input has no standalone adjusted-price column. A causal adjusted coordinate is therefore
chained from each valid session's `close / preclose`; intraday high and low are mapped by
`high / close` and `low / close`. This prevents raw split/dividend reference changes from
being mistaken for market drawdowns. It is a reference-price return coordinate, not a claim
of a fully archived total-return series.

Important limitations are PIT-B rather than PIT-A corporate-action revision history, no
explicit listing-date field (120 valid trading sessions is the listing-age proxy), no use of
minute/L2 execution, and no event/fundamental collapse filter. Industry and market fields are
available but are not needed for the core V1 definitions. The existing registry activation
loader is reused; DuckDB reads the already normalized table directly rather than rebuilding
the production causal panel.

## Universe and chronology

- Warm-up: 2018-01-02 onward; signal evaluation starts 2020-01-02.
- Current signal row must be hard-valid, trading, non-ST, and have positive OHLCV/amount and
  known turnover.
- At least 120 valid trading sessions and CNY 10 million 20-session median amount are required.
- No invalid-lineage row may fall between the oldest and newest observations of the 60-session
  feature window.
- A close-based signal never enters at that close. Entry is the next listed row's open only if
  that row is hard-valid, trading, non-ST, current-day tradable, and not buy-blocked at open.
- Horizons count subsequent trading sessions. A result is retained only when the full
  20-session path has known required lineage; the same complete sample is used for 5/10/20
  comparisons.
- Core events are de-clustered: a stage fires only after the same condition has not appeared
  in the previous five trading sessions. Raw nested-condition results are also reported.

## Fixed definitions

`LOW (A)`:

- adjusted close drawdown from its trailing 60-session maximum is at most -15%; and
- adjusted close is no more than 5% above the trailing 60-session adjusted intraday low.

`DRY-UP (B)` is A plus:

- 5-session mean amount / 20-session median amount <= 0.55.

`STABILIZATION (C)` is B plus all of:

- adjusted 3-session return >= -2%;
- the minimum adjusted low over sessions t-2..t is no more than 1% below the minimum over
  t-5..t-3; and
- 3-session downside impact does not exceed its 20-session baseline, where downside impact is
  `sum(max(-close/preclose return, 0)) / sum(turnover_fraction)`.

`CONFIRMATION (D)`:

- a C setup occurred in the previous five trading sessions; and
- current adjusted close exceeds every adjusted close in the previous five sessions.

`SECOND-LOW`:

- the first low is the minimum adjusted intraday low 10–40 sessions before the current row;
- the current adjusted low is 97%–105% of that first low and is at the current 3-session low;
- the exact intervening adjusted high rebounded at least 8% above the first low;
- only the first qualifying revisit of a given first low is retained; and
- contraction means current 3-session mean amount / first-low 3-session mean amount <= 0.60;
  the explicit comparison group has a ratio >= 0.80.

These values were chosen once from the economic statement. They were not searched or changed
after observing results.

## Outcomes

Returns start at the legal next-session open and end at adjusted close after 5, 10, or 20
trading sessions. MFE/MAE use adjusted intraday highs/lows over the same entry-to-horizon
window. Reported outcomes are gross of fees, slippage, and market impact. This is appropriate
for signal discovery but not a tradable performance claim.

Continuous diagnostics use descriptive quintiles only. The controlled dry-up table first
stratifies LOW events by time block and drawdown quintile, then forms dry-up quintiles inside
those strata. These ranks are diagnostics, not deployable thresholds.

