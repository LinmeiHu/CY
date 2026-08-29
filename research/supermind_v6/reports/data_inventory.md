# SuperMind V6 market-data inventory

Audit date: 2026-08-28 (Asia/Shanghai)

Scope: only the frozen SuperMind V6 strategy pool (152 ETFs), `000852.SH`,
`510300.SH`, and `000300.SH`. This inventory records what is already present before
any V6-specific download or build. It does not activate or modify any production
asset.

## Post-inventory QMT result

The table below remains the immutable pre-build inventory. A later bounded QMT
probe changed the selected build path without changing any production asset:

- The running Guojin MiniQmt and `xtquant` local RPC were connected successfully.
- Three-symbol canary (`510300.SH`, `159915.SZ`, `588000.SH`) returned 5/5 daily
  sessions and 1,205/1,205 minute rows per symbol for 2026-08-17..2026-08-21.
- The completed QMT build now has 152/152 ETF daily partitions plus both index
  anchors, covering 2005-02-23..2026-08-28 with 212,679 ETF daily rows.
- QMT 1m retention under this client/account begins around 2025-08-27 despite a
  1990 request. The isolated critical-bar layer has 152/152 symbol partitions and
  109,187 rows, but is not full-history minute data.
- The normalized QMT dataset is under the Git-ignored
  `research/supermind_v6/data/market_data_qmt_v1/`. The earlier Eastmoney partial
  build remains preserved separately under `market_data_v1/`.

Current acceptance facts live in `data_readiness.md` and the QMT manifest; the
pre-build conclusions below must not be read as the current coverage result.

## Frozen input and parsed scope

- Strategy: `research/supermind_v6/strategy/SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py`
- Strategy SHA-256: `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`
- `context.pool_raw`: 152 rows, 152 unique raw codes.
- Universe SHA-256 (raw codes in strategy order joined by LF, no terminal LF):
  `0a647dba2e5ef80088c9ec9c9ebdb889b1744ddb1686d0e20867a9a7059f98c3`.
- Exchange mapping required by the strategy: `5xxxxx -> .SH`, `1xxxxx -> .SZ`.
  The parsed pool contains 87 Shanghai and 65 Shenzhen codes.

## Repository data governance and storage conventions

- `configs/data_asset_registry.json` is the existing source-of-truth registry.
  Only registered uses are allowed; unknown lineage and unavailable-at facts fail
  closed. No V6 work may silently substitute a different local copy.
- `src/cyq_game/data/quant_adapter.py` provides bounded, fail-closed adapters for
  registered raw market data. Its scope guard is deliberately small and it does
  not make an otherwise ineligible asset valid for this research.
- Existing raw/processed data lives outside Git. The repository `.gitignore`
  pattern `data/` also ignores `research/supermind_v6/data/`; scripts, schemas,
  small manifests and reports can be force-included only if explicitly intended.
- Installed libraries include pandas 2.2.3, PyArrow 19.0.0, DuckDB 1.5.2,
  BaoStock 0.9.10, AkShare 1.18.56, and Tushare 1.4.29. Their presence is not
  evidence that a provider or endpoint has been accepted.
- Existing BaoStock tools support immutable responses, hashes, resumability and
  bounded sessions. The current full-market delta code is A-share-specific and
  rejects ETF codes, so it cannot be reused unchanged. Production code will not
  be modified for V6.
- No API token is stored or required by the audited local assets. No credential
  was read or printed during this audit.

## Existing assets

| Asset | Registry status | Physical location | Coverage / fields | V6 reuse decision |
|---|---|---|---|---|
| QD-001 unadjusted daily bars | `RESEARCH_CONDITIONAL`, PIT-B | `/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily` | Overall: 2004-01-02..2026-08-14, 5,736 `*.none.parquet` symbols. `trade_date,symbol,adjust,OHLC,preclose,volume,amount,turnover_rate`. Raw prices; record-level `available_at` absent. | Pool coverage is only 21/152. Raw OHLC, volume and amount are potentially reusable through an independent V6 snapshot/normalizer, but QD-001 is explicitly blocked as standalone backtest input. `turnover_rate` must never be used as SuperMind turnover. |
| QD-001 qfq side copies | not eligible price facts under QD-001 | same directory, `*.qfq.parquet` | Same 21 pool symbols observed; provider adjustment provenance is not sufficient to prove SuperMind `fq='pre'` equivalence. | QA/reference only until an independently documented adjustment contract passes. |
| QD-003 index daily bars | `RESEARCH_CONDITIONAL`, PIT-B | `/Users/linmei/Downloads/workspace/quant/data/lake/index_daily` | `csi000300`: 4,939 rows, 2006-04-20..2026-08-14. `csi000852`: 4,696 rows, same date range. OHLC, volume, amount; no record-level `available_at`. | Both required anchors exist physically and can be frozen/normalized after gates. Not standalone strict-PIT evidence as-is. |
| QD-004 canonical A-share 1m | `RESEARCH_CONDITIONAL`, PIT-B | `/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813` | 2000-06-09..2026-08-12, raw/unadjusted OHLCV/amount. Approximately 40 GiB. | Bounded 2025 queries for `510300`, `159915`, `512880`, and `588000` returned zero rows. It is an A-share asset, not an ETF minute source. |
| QD-006 alternative minute copies | `QA_ONLY`, PIT-C | local lake QMT/TDX/BaoStock copies | Vendor-specific 1m/5m, not auto-fallback eligible. | Existing BaoStock 5m directory is A-share code-only. No V6 ETF coverage established; QA only. |
| QD-007 historical security universe | `DISCOVERY_ONLY`, candidate not materialized | none | BaoStock `query_all_stock(date)` bounded probes only. No immutable full snapshots, causal `available_at`, or activated PIT master. | Cannot be used for V6 universe construction or survivorship claims. A V6-specific immutable ETF master/snapshot source is missing. |
| CY-006 daily PIT-B v2 | `RESEARCH_CONDITIONAL` | `/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily` | 2018-01-01..2026-08-12, A-share production research table. | Bounded query for the 21 locally present ETF codes returned zero rows. Do not couple V6 to this production schema. |
| CY-008 minute PIT-B v2 | `RESEARCH_CONDITIONAL` | `/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2` | A-share causal five-minute execution features. | No ETF coverage; production schema remains read-only and out of scope. |
| Local security master | not a V6 PIT ETF master | `/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet` | 5,891 rows; stock-oriented fields include symbol, name, exchange, status, list/delist date. | Exact pool-code matches: 0/152. Not usable for V6 ETF point-in-time membership. |
| Local trade calendar | local metadata; independent acceptance still required | `/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet` | 8,797 unique dates, 1990-12-19..2026-12-31. | Physically sufficient for date arithmetic, but source/provenance and completeness against the selected V6 provider must be validated before acceptance. |

## QD-001 coverage inside the frozen 152-ETF pool

The following 21 raw daily partitions exist. `invalid` counts rows where close,
volume, or amount is null; it is zero in this bounded audit. The final two young
funds have fewer than the strategy's required 121 observations.

| raw code | rows | first date | last date | invalid | unique dates |
|---|---:|---|---|---:|---:|
| 510300 | 3,385 | 2012-05-28 | 2026-05-06 | 0 | 3,385 |
| 512880 | 2,359 | 2016-08-08 | 2026-04-28 | 0 | 2,359 |
| 159915 | 3,493 | 2011-12-09 | 2026-05-06 | 0 | 3,493 |
| 510500 | 3,188 | 2013-03-15 | 2026-05-06 | 0 | 3,188 |
| 512100 | 2,301 | 2016-11-04 | 2026-04-28 | 0 | 2,301 |
| 510880 | 4,683 | 2007-01-18 | 2026-04-28 | 0 | 4,683 |
| 510050 | 4,696 | 2007-01-04 | 2026-05-06 | 0 | 4,696 |
| 512480 | 1,668 | 2019-06-12 | 2026-04-28 | 0 | 1,668 |
| 512400 | 2,098 | 2017-09-01 | 2026-04-28 | 0 | 2,098 |
| 512010 | 3,039 | 2013-10-28 | 2026-04-28 | 0 | 3,039 |
| 515220 | 75 | 2026-01-05 | 2026-04-28 | 0 | 75 |
| 512690 | 1,694 | 2019-05-06 | 2026-04-28 | 0 | 1,694 |
| 159870 | 1,250 | 2021-03-03 | 2026-04-28 | 0 | 1,250 |
| 512800 | 2,119 | 2017-08-03 | 2026-04-28 | 0 | 2,119 |
| 512760 | 1,668 | 2019-06-12 | 2026-04-28 | 0 | 1,668 |
| 512660 | 2,359 | 2016-08-08 | 2026-04-28 | 0 | 2,359 |
| 515790 | 1,297 | 2020-12-18 | 2026-04-28 | 0 | 1,297 |
| 159980 | 1,536 | 2019-12-24 | 2026-04-28 | 0 | 1,536 |
| 512200 | 2,082 | 2017-09-25 | 2026-04-28 | 0 | 2,082 |
| 515030 | 1,492 | 2020-03-04 | 2026-04-28 | 0 | 1,492 |
| 515210 | 75 | 2026-01-05 | 2026-04-28 | 0 | 75 |

The other 131 pool symbols have no QD-001 raw daily partition. Dates above are
physical coverage, not proof of listing date, delisting date, or strict PIT fitness.

## What can be reused safely

1. The frozen strategy itself can be parsed deterministically for the exact pool.
2. QD-003 supplies bounded source material for both required index series.
3. QD-001 supplies bounded raw daily source material for 21 ETFs, with amount
   physically present, subject to V6-specific snapshot and unit validation.
4. The local calendar can be cross-validated and snapshotted, but cannot yet be
   accepted solely because a Parquet file exists.
5. Existing patterns for atomic files, SHA-256 inventories, explicit source
   lineage, checkpoints, retries and fail-closed validation can be copied into an
   isolated `research/supermind_v6/` implementation.

## Missing or unresolved

- Raw daily OHLCV and CNY amount for 131/152 ETFs.
- An adjustment factor/event source that can reconstruct pre-adjusted OHLC while
  preserving raw prices. `SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE: UNVERIFIED`.
- A point-in-time ETF security master with audited list/delist dates and immutable
  source snapshots. Current-master backfill is prohibited.
- ETF 1m data, or even an accepted critical-bar source, for 09:30 open, 14:57 bar
  open and final official close.
- True opening-auction match data. Daily open and 09:30 bar open are not accepted
  proxies.
- Proof that daily adjusted prices and 14:57 intraday prices share one basis.
- A V6-specific immutable source manifest, normalized schemas, coverage audit,
  validation entry point and sample evidence.
- Exact provider definitions for volume unit, amount currency/unit, suspensions,
  missing bars, corporate actions, adjustment revisions and endpoint retention.

No download or V6 dataset build had been started when this inventory was written.
