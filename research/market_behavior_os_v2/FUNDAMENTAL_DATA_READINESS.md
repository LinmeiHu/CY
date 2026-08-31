# PIT fundamental data readiness — cycle 006

Audit date: 2026-08-31. This is a data-readiness result, not a fundamental-alpha
result. No post-2023 market outcome or CY-011 asset was opened.

## Storage decision

The read-only audit found one plausible large research volume:
`/Volumes/quant`, mounted from `/dev/disk9s1`, size 3.6 TiB, about 3.6 TiB
available, and owned writable by the current user. No data root was created and
no acquisition was performed because no bounded download would repair the
missing historical revision semantics.

## Readiness matrix

| Field family | Existing source | Physical coverage | Availability timing | Revision/restatement semantics | Units/consistency | 2018--2023 alpha use |
|---|---|---|---|---|---|---|
| Publication dates | Legacy Eastmoney `yjbb_em` current snapshot | 79 report-period files through 2023-09-30; 370,639 rows | Date-only `notice_date`; no intraday time | No historical snapshot/revision identity; 1,247 rows have notice dates after 2023-12-31 | Calendar dates; 61 missing | `BLOCKED` |
| EPS / earnings | Same | 355,716 non-null rows | Tied only to current row's notice date | Current/restated value may be attached to an earlier notice; original released value unavailable | CNY/share, but cumulative-vs-quarterly period interpretation is not independently frozen | `BLOCKED` |
| Book equity per share | Same | 352,056 non-null | Same | Same | CNY/share; capital-coordinate consistency unresolved | `BLOCKED` |
| ROE / profitability | Same | 337,314 non-null | Same | Same | Percentage points; period comparability unresolved | `BLOCKED` |
| Operating cash flow | Same | 355,054 non-null | Same | Same | CNY/share; cumulative-period semantics not independently frozen | `BLOCKED` |
| Gross margin | Same | 360,282 non-null | Same | Same | Percentage points; financial-sector missingness is structural | `BLOCKED` |
| Revenue/profit growth | Same | 335,452 / 337,026 non-null | Same | Same | Percentage points; denominator and restatement policy unresolved | `BLOCKED` |
| Balance sheet / assets / liabilities | None registered | None | None | None | None | `UNAVAILABLE` |
| Investment / asset growth | None registered | None | None | None | None | `UNAVAILABLE` |
| Faithful accruals | None registered | None | None | None | None | `UNAVAILABLE` |
| Shares / float capitalization | QD-009 plus CY-006 | 447,495 capital rows / daily 2018--2026 bridge | Effective and announcement dates are both causal | Frozen input identity, but registry blocks standalone backtest use | Shares and CNY market data | Valuation denominator support only after a fundamental numerator is activated |
| PIT industry | CY-006 | Daily 2018--2026 | Available at daily decision time | Frozen PIT-B lineage | Provider industry label | `READY` as context/control |

## Fail-closed decision

`QD-011` is registered only as `CANDIDATE_NOT_MATERIALIZED`. It lacks row-level
`available_at`, immutable snapshot identity, and revision identity, and its
allowed uses stop at bounded probes and adapter design. The legacy files do not
repair these gates. Prior work using them explicitly states that it did not test
whether reported fundamentals were subsequently restated.

CNINFO exposes original official announcements and financial reports, but a
usable cross-sectional 2018--2023 dataset would require enumerating filings,
capturing publication timestamps, preserving amendments, parsing statement
versions, normalizing accounting periods/units, and reconciling restatements.
That is a fundamental-data platform rather than minimum acquisition.

Cycle status: `PIT_FUNDAMENTAL_DATA_BLOCKED`. Book-to-market, earnings yield,
cash-flow yield, profitability, investment, quality, accrual, and growth priors
are not screened. No null filling, current-snapshot substitution, conservative
fixed lag, or provider-latest value is used as a historical fact.
