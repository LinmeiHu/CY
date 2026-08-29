# SuperMind V6 market-data contract

Version: `v6-market-data-contract-1`

This contract is derived from the frozen strategy, not from a proposed local
backtester. Unknown fields or lineage fail closed. A row that violates a required
contract is excluded rather than repaired, filled, clipped or substituted.

## Scope and identity

- Strategy source and SHA-256 must match the manifest.
- The ETF pool must be parsed from the strategy AST. A copied/manual pool is not
  authoritative.
- Expected universe is exactly 152 unique raw codes: 87 Shanghai and 65 Shenzhen.
- Canonical mapping is `5xxxxx -> xxxxxx.SH`, `1xxxxx -> xxxxxx.SZ`.
- Required non-pool series are `000852.SH` (entry anchor), `510300.SH` (exit
  anchor and tradable pool member), and `000300.SH` (benchmark).

## Availability and point-in-time rules

`trade_date` describes the session. `available_at` describes when a completed
fact may first be consumed. Daily facts are never usable within their own session;
the normalized conservative bound is the following calendar day at 00:00
Asia/Shanghai. This is a causal completed-bar bound, not proof that Eastmoney or
Sina preserves archival vendor vintages.

Every row must carry or inherit:

```text
source
source_endpoint
capture_at
available_at
snapshot_id
raw_response_sha256 or source_file_sha256
```

The selected build extracts QMT `dividend_type=none` and `front` results into
immutable Parquet partitions. Each row carries `source`, `source_endpoint`,
`capture_at`, `available_at` and `snapshot_id`; each partition has a request
sidecar and SHA-256. QMT's proprietary cache is external and cannot itself be
content-hashed, so this is PIT-B research evidence rather than archival PIT-A.
Revised historical results require a new capture and partition hash.

ETF eligibility for date `d` requires all of:

```text
raw_code is in the frozen 152-code pool
list_date is known from an exchange source
list_date <= d
delist_date is null or d <= delist_date
a VALID daily row exists on d when a cross-sectional value is needed
the required trailing observation count is present
```

Today’s ETF list must never be expanded backward before `list_date`. A missing
list/delist fact is `MISSING`, not inferred from a name. Current-listed status is
recorded as-of capture; it does not prove historical archival membership by
itself. Exact code reuse or historical delisting would require a separate dated
exchange snapshot and must fail closed until resolved.

## ETF security master

Required schema:

```text
raw_code: string(6)
symbol: string
exchange: SH | SZ
name: string
list_date: date
delist_date: nullable date
security_type: ETF
status_as_of_capture: listed | delisted | unknown
list_date_source: string
source_endpoint: string
capture_at: timestamp[Asia/Shanghai]
snapshot_id: string
```

The security master uses the Shanghai Stock Exchange `FUND_LIST` public result
and the Shenzhen Stock Exchange ETF fund-list workbook. Both were snapshotted
through their public endpoints. QMT is the selected OHLCV provider. BaoStock
remains allowed through the user's VPN, but its bounded ETF probes returned zero
rows and it is not silently mixed into this dataset.

QMT capability evidence: the official XtData documentation defines `1m` and `1d`
K-line periods, `download_history_data`, `get_market_data_ex`, and
`dividend_type=none/front`; the official floor-fund page explicitly demonstrates
historical ETF download. Runtime canary and final-close reconciliation remain the
acceptance evidence for this particular Guojin client/account.

## ETF daily schema

One row per `(symbol, trade_date)`:

```text
trade_date: date
symbol: string
raw_code: string(6)
exchange: SH | SZ
row_status: VALID | MISSING | SUSPENDED | NOT_LISTED | DELISTED |
            NONPOSITIVE_VOLUME | NONFINITE
raw_open, raw_high, raw_low, raw_close: float64
pre_adj_open, pre_adj_high, pre_adj_low, pre_adj_close: float64
adj_factor_close_ratio: float64
volume_raw: float64
volume_unit: lot_100_shares
volume_shares: float64
amount_cny: float64
available_at: timestamp[Asia/Shanghai]
source, snapshot_id: string
```

QMT-native `成交量` is retained unchanged as `volume_raw`. The V6 normalizer
normalizer records its observed unit as 100-share lots and also writes
`volume_shares = volume_raw * 100`. The unit assertion must be checked using
`amount_cny / (raw_close * volume_raw)` near 100 on liquid samples; it may not be
accepted solely from the Chinese field name. The strategy's volume-location rule
uses a within-symbol ordering, so a constant unit conversion does not change its
argmin; nevertheless both representations remain explicit.

QMT `amount` maps to `amount_cny`. The compatibility layer for frozen
SuperMind `history(..., 'turnover')` maps exactly:

```text
SuperMind turnover -> amount_cny
```

It never maps to `换手率`/`turnover_rate`. The 20-day average threshold
`20_000_000` therefore means CNY.

No OHLC, volume, amount, or minute value is forward-filled. A date without a
provider row remains absent and is classified by the coverage audit. Zero or
missing volume is not replaced; the strategy's own fail-closed behavior remains
observable.

## Price adjustment

Raw QMT OHLC (`dividend_type=none`) and QMT front-adjusted OHLC
(`dividend_type=front`) are retained side by side. For diagnostic use:

```text
adj_factor_close_ratio = pre_adj_close / raw_close
```

This derived ratio is not an independently sourced corporate-action factor. QMT
front adjustment is requested independently for daily and 1m; missing bars are
never manufactured. Provider history can be revised, so capture time and the
partition hash remain part of dataset identity.

```text
SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE: UNVERIFIED
```

No direct official/test artifact proves that QMT `front` exactly equals
SuperMind `fq='pre'` on every ETF event and historical decision date. A later
acceptance requires SuperMind reference output across audited ETF distributions
or share conversions.

## Daily history and suspensions

- Store all provider history from each ETF’s listing date through the configured
  last complete session, not merely 140 rows.
- `context.min_history = 121`; report the first date on which each symbol has 121
  valid close observations. A young ETF is not defective merely because it has
  not yet accumulated 121 observations.
- `context.history_days = 140` is a request window, not a storage truncation rule.
- Volume for MINVOL uses exactly `t-30..t-1`; signal-day volume is excluded.
- No forward-fill is allowed. Provider rows with finite positive OHLC but zero
  volume/amount remain explicit nonpositive-volume states, not synthetic bars.
- If a provider omits suspension dates and no independent status flag exists, the
  date is `MISSING_OR_SUSPENDED_UNRESOLVED`; it cannot be silently labelled one or
  the other.

## Market anchors and benchmark

`000852.SH` and `000300.SH` require `trade_date`, raw daily close, source lineage,
and completed-bar availability. The former gates new entries via MA15; the latter
is reporting-only. `510300.SH` is governed by the ETF daily and minute contracts
and additionally gates exits via MA20.

The isolated candidate build may use the already registered QD-003 snapshot or a
separately frozen Sina response, but may not splice providers without an explicit
source-boundary field and reconciliation. The selected build records one source
per series.

## Minute and execution contract

Full 1m schema, if and when an accepted historical source becomes available:

```text
trade_date: date
datetime: timestamp[Asia/Shanghai]
symbol, raw_code, exchange
raw_open, raw_high, raw_low, raw_close
volume_raw, volume_unit, volume_shares, amount_cny
price_basis
bar_status
available_at, source, snapshot_id
```

Required critical facts per normal ETF session are distinct:

1. 09:30 one-minute bar **open** for the frozen fallback path.
2. 14:57 one-minute bar **open** for the causal pseudo-close signal.
3. 15:00/final one-minute bar close and official daily close for close execution.

Missing 14:57 open must not be replaced with the bar close or official close.
The 14:57 price is a signal input, never the sell execution price. Missing 15:00
bar must not be manufactured from a daily row when minute volume/fill semantics
are being tested.

The opening-auction match, official daily open and 09:30 bar open are separate
facts. With the currently audited sources:

```text
OPEN_AUCTION_EXACT_REPLICATION: UNVERIFIED
OPEN_BAR_09_30_REPLICATION: PARTIAL (QMT 2025-08-27..2026-08-28; 175 gaps)
OPEN_BAR_14_57_REPLICATION: YES within the QMT retention window
FINAL_CLOSE_BAR_REPLICATION: YES within the QMT retention window
```

The QMT critical layer contains only the three requested bar keys, not a full 1m
export. MiniQmt retains the underlying 1m cache, but this client/account returned
only about 244 recent sessions even when requested from 1990. The artifact is
therefore labelled `critical_execution_bars_only`, never full-history minute.

## Daily/minute price-basis gate

The strategy appends current 14:57 `bar.open` to pre-adjusted daily closes. QMT
`front` is requested separately for both daily and 1m. Across every exported
overlap, raw 15:00 close equals raw daily close and front-adjusted 15:00 close
equals front-adjusted daily close (zero validation mismatches).

```text
DAILY_MINUTE_PRICE_BASIS_VALID: YES (QMT overlap only)
SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE: UNVERIFIED
```

This proves internal QMT basis consistency, not equivalence to SuperMind. The
derived ratio is not used to synthesize missing minute bars.

## Trading calendar

Normalized schema:

```text
trade_date: date
is_trading_day: true
calendar_source: string
snapshot_id: string
```

The calendar must be unique and increasing and must support previous/next session,
first session of a new ISO week, and last actual session within a Monday–Sunday
week. Weekends, statutory holidays and exceptional closures are derived only from
the explicit trading-date set; weekday arithmetic is forbidden.

The selected calendar is QMT `get_trading_dates(SH)` because this Guojin client
does not implement the newer holiday/calendar control call. It must match the
Sina/local reference on their common range, include the requested end date, and
contain every VALID market row date.

## Storage and reproducibility

Large payloads live only under the Git-ignored directory:

```text
research/supermind_v6/data/market_data_qmt_v1/
```

Trackable scripts, tests, small manifest and reports live outside that ignored
subtree under `research/supermind_v6/`. Parquet is partitioned by logical dataset
and symbol. Writes use a temporary sibling and atomic replace. Existing VALID
partitions whose manifest hash and requested end date match are skipped; retries
do not append duplicates.

Manifest identity includes provider/version/endpoint, request parameters, capture
time, strategy and universe hashes, schemas, row counts, bytes, per-symbol date
coverage, source response hashes, missing/duplicate counts and validator output.
No API token is hard-coded or required by this candidate build.

## Acceptance gates

The data foundation is ready for V6 feature reconstruction only when all are true:

- 152/152 exchange master rows and daily partitions pass.
- No valid daily row predates list date; no future-listed symbol enters history.
- Raw/qfq row keys match or every mismatch is explicitly excluded.
- Amount is validated as CNY and never confused with turnover rate.
- At least 121 valid observations are correctly reported, not fabricated.
- Both anchors and the benchmark cover the requested interval.
- Calendar tests pass.
- Historical 09:30 open, 14:57 open and final close coverage meet the declared
  research interval.
- Opening-auction limitation is explicit.
- Corporate-action adjustment equivalence and daily/minute price basis pass.
- Real cross-exchange and event samples pass.

Any failed gate yields `V6_DATA_READY: NO` while preserving the useful accepted
subsets and exact blockers.
