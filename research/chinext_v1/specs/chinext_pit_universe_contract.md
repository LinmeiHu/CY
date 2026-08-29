# ChinNext V1 canonical PIT universe contract

## Scope

This contract governs Phase 1 security-date eligibility only. It does not define
B60, FULL40, MINVOL, RS, portfolio construction, exits, or execution.

Unknown critical facts fail closed. A code prefix, a current survivor list, a
missing OHLCV row, or a current security name is never silently promoted to a
historical point-in-time fact.

## Canonical security-date record

An eligibility decision for symbol `s` on signal session `t` is the join of one
date-effective identity record, one explicit exchange calendar, and date-varying
daily facts. Every consumed fact must have `available_at <= decision_at`.

Required normalized fields:

| Field | Type | Fact class | Contract |
|---|---|---|---|
| `symbol` | canonical string | STATIC / DATE-EFFECTIVE | Exchange-qualified, e.g. `300750.SZ`; prefix is validation only. |
| `trade_date` | date | DATE-VARYING PIT | Exchange session being evaluated. |
| `board` | enum | DATE-EFFECTIVE | Must equal canonical `CHINEXT`; must come from a dated security master, not prefix inference. |
| `membership_start` | date | DATE-EFFECTIVE | First date on which the normalized master asserts ChiNext membership. |
| `membership_end_exclusive` | nullable date | DATE-EFFECTIVE | First date no longer eligible. A raw last-listed date must be normalized explicitly. |
| `list_date` | date | STATIC SECURITY FACT | Official/accepted first-listing date with source and availability evidence. |
| `delist_date` | nullable date | STATIC SECURITY FACT | Retained raw source fact; its inclusive/exclusive semantics must be mapped to `membership_end_exclusive`. |
| `listed_trading_days` | integer | DERIVED | Count from first exchange session on/after `list_date` through `t`, inclusive. |
| `risk_warning` | nullable bool | DATE-VARYING PIT | True for every covered ST, `*ST`, or risk-warning state; unknown is not false. |
| `suspended` | nullable bool | DATE-VARYING PIT | Exchange/provider state fact; a missing bar alone is insufficient proof. |
| `tradable_buy` | nullable bool | DATE-VARYING PIT | Side-specific ability at the stated observation/execution scope. Unknown blocks entry. |
| `tradable_sell` | nullable bool | DATE-VARYING PIT | Preserved separately; Phase 1 does not implement a sell state machine. |
| `amount_cny` | float | DATE-VARYING PIT | Daily transaction amount in RMB; ambiguous `turnover` is not accepted. |
| `amount_unit` | enum | STATIC FIELD CONTRACT | Must be exactly `CNY` before the 100m threshold is applied. |
| `source` | string | BOTH | Provider/dataset identity; nonempty. |
| `source_version` | string | BOTH | Immutable snapshot, manifest, capture, or version identity; nonempty. |
| `available_at` | timezone-aware timestamp | BOTH | Earliest causal consumption time. Missing/naive timestamps fail. |
| `hard_valid` | nullable bool | DATE-VARYING PIT | Where governed by the registry, only exact true may add a symbol to the pool. |

`asof` means the source record was effective and available for this security and
date; it does not mean “latest record currently visible.” Static facts may be
reused across dates only when their own source contract establishes when they
became knowable. Capture time in 2026 cannot be relabeled as historical
`available_at`.

## Static versus date-varying facts

STATIC SECURITY FACT:

- canonical symbol/exchange identity;
- accepted listing date;
- provider field/unit definitions.

DATE-EFFECTIVE or DATE-VARYING PIT FACT:

- ChiNext board membership interval;
- listed/delisted eligibility interval;
- ST, `*ST`, and other risk-warning state;
- suspension and side-specific tradability;
- daily CNY amount;
- source version and availability for each effective observation.

A present-day name containing `ST` cannot reconstruct a historical risk-warning
series. Conversely, a historical `is_st=false` field may be mapped to
`risk_warning=false` only if the source contract proves that the field covers all
excluded warning categories. Otherwise canonical `risk_warning` remains unknown.

## Board membership

Formal membership requires a time-qualified security master assertion
`board=CHINEXT`. `300xxx` and `301xxx` are only sanity checks. They may detect an
inconsistent master record but cannot create one.

The tracked current-survivor artifact is explicitly
`NON_PIT_CURRENT_SURVIVOR`. It may be inspected for current coverage statistics,
but it cannot populate any historical `membership_start`, `membership_end`, or
board fact. A `current_state_only` record is rejected for a different signal date.

## Listing age

The unique Phase 1 rule is:

```text
first_session = first explicit exchange trading session >= list_date
listed_trading_days(t) = count(first_session ... t), inclusive
eligible_age = listed_trading_days(t) >= 180
```

Signal session `t` counts. The 180th observable exchange session therefore passes;
the 179th fails. Calendar-day arithmetic is forbidden. If `t` is absent from the
explicit calendar or the calendar does not cover `list_date..t`, the age is
unknown and fails closed.

The canonical normalized `membership_end_exclusive` is the first ineligible date.
Thus `t >= membership_end_exclusive` fails. Source adapters must document whether a
raw `delist_date` is the last listed date or the first unlisted date; this layer
does not guess.

## Risk-warning and tradability gates

For entry-universe eligibility on `t`:

```text
risk_warning(t) must be exactly false
suspended(t) must be exactly false
tradable_buy(t) must be exactly true
hard_valid(t) must be exactly true where the registry requires it
```

Unknown values fail. `OBSERVED_DATA_AVAILABILITY` and
`EXCHANGE_TRADABILITY_FACT` remain separate: a valid OHLCV row is not by itself a
complete buy/sell permission, and a missing row is not by itself proof of a
suspension.

The current local evidence is partial:

- QD-002/CY-006 contain daily `trade_status`, `is_st`, limit and blocked-open
  fields; CY-006 adds row-level `available_at`, `snapshot_id`, and `hard_valid`.
- The inspected source path maps BaoStock daily `isST` to `is_st`. No inspected
  contract proves that it covers every required risk-warning subtype.
- BaoStock `query_all_stock(date)` discovery probes expose `tradeStatus`, but
  QD-007 remains `DISCOVERY_ONLY` and cannot be activated by this research code.

Accordingly, an adapter may preserve these facts for validation, but canonical
`risk_warning` must remain unknown unless the complete mapping is proven.

## Turnover20

The liquidity input is `amount_cny`, not turnover rate and not an ambiguously named
`turnover` field.

```text
window = the last 20 explicit exchange sessions ending at signal session t
turnover20 = mean(amount_cny for all 20 sessions)
eligible_liquidity = turnover20 >= 100,000,000 CNY
```

Signal day `t` is included because this Phase uses completed daily observations and
the later strategy may not fill on `t`. Each of the 20 sessions needs one visible,
hard-valid CNY amount fact. Missing observations, NaN/infinite/negative values,
unknown units, unknown lineage, or fewer than 20 sessions fail closed. An explicit
zero amount is numerically retained; current-session suspension/tradability gates
separately reject entry.

Evidence for the unit is both contractual and empirical: CY-006 is derived from
registered raw daily amount, and the bounded 2020 ChiNext sample has median
`amount / (close * volume) = 1.0000055353303303`, consistent with volume in shares
and amount in CNY. The canonical adapter still requires the explicit unit label.

## Market anchor

The only permitted anchor key is `399102.SZ`. Missing exact history raises an
error. `399006.SZ`, `000852.SH`, and every other index are forbidden fallbacks.

The Phase 1 QMT probe identifies `399102.SZ` as `创业板综` and returns daily rows
from 2010-06-01. QMT raw and `front` OHLC are identical in that probe, consistent
with consuming an unadjusted index-level series. The provider rows have no
`available_at` field, so later normalization must attach a conservative completed-
bar availability and freeze the extracted dataset/manifest before research use.

## Fail-closed result

An eligible result requires every identity, age, risk, suspension, buy-tradability,
amount, unit, lineage, availability, and validity gate to pass. The implementation
returns explicit reason codes for every failure and computes no strategy signal,
portfolio target, order, fill, or return.
