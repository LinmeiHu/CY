# ChinNext V1 free historical-state acquisition and Gate A/B closure

## Decision

The exact free-source bounded input is complete for `2017-04-12..2021-12-31`.
Gate A and Gate B both pass. No active historical-state blocker remains, and it is
safe to preregister Gate C. Gate C, Phase12B4, strategy replay, trades, NAV, and
performance evaluation were not executed.

This is an exact-artifact `BOUNDED_EFFECTIVE_STATE_PIT_B` authorization. BaoStock
does not expose record-level historical `available_at` or a supplier
revision-vintage chain, so `STRICT_PIT_A=NO` and
`revision_history_complete=false` remain permanent limitations of this input.

## Minimum-sufficient implementation

The implementation reuses the repository QD-003 calendar, bounded authorization,
manifest, parquet, fail-closed, and test patterns. It adds one frozen acquisition
spec, one data-driven official-event artifact, one narrow builder, one tracked
manifest, and two normalized parquet files. It does not add a framework, generic
security master, registry layer, daily database, strategy adapter, or production
abstraction.

Raw evidence is stored once as deterministic gzip JSONL for the complete
date-specific denominator, stock basic, and minimum daily state. The normalized
output is only:

- `security_master.parquet`: 1,098 bounded historical identities;
- `daily_historical_state.parquet`: 924,549 date-membership/state rows, including
  listing age, ST/*ST subtype, full-session suspension, and the conservative next
  QD-003 `earliest_safe_use_date`.

The ignored raw/parquet data are bound by the tracked
`chinext_v1_free_historical_state_manifest.json`. A second complete normalized
build produced byte-identical files.

## Acquisition result

BaoStock package `0.9.1` (module string `00.9.10`) supplied all 1,153 required
QD-003 sessions with zero failed snapshots. The complete denominator contains
5,002,929 rows; its yearly control snapshots vary from 3,757 rows on 2017-04-12
to 5,147 rows on 2021-12-31, with distinct sorted-code-set hashes at every sampled
year boundary. The state acquisition contains 925,702 rows for all 1,099 raw
candidate codes. There are no missing denominator/state joins, trade-status
conflicts, duplicate keys, unknown required state values, or list/out-boundary
conflicts.

The official Shenzhen code-semantics page states `300000-399999`. A complete raw
scan found 1,444 codes in that numeric range, of which exactly 1,099 were
BaoStock `type=1`; no `type=1` candidate fell above the capture filter's upper
bound. Thus the full official-range audit adds zero missing state requests.

## Identity, listing, delisting, and non-survivors

The systematic identity scan grouped securities only when `ipoDate`, row count,
and the exact identity-relevant daily sequence (`date`, `volume`, `tradestatus`,
`isST`) matched. It found exactly one anomaly: `300114` and `302132`. Their
identity-relevant histories match, while BaoStock has small source-format
differences in some `amount` values; the first observed difference is 2019-02-20
(`63016557.4800` versus `63016557.0000`). No tolerance or fill was applied.

CNINFO document SHA-256
`dd68049c48df826848f361fd9e7b23dd20b6805144a2e5bc36e54db638611488`
establishes the `300114 -> 302132` code change effective 2025-02-17. Therefore
`302132.SZ` has zero normalized rows in 2017-2021 and `300114.SZ` retains all
1,153 sessions. This boundary is data, not a source-code hardcode.

The normalized history contains 1,058 current-survivor identities and 40 true
historical non-survivors. It retains 478 target-period new listings and eight
target-period delistings. Positive controls pass exactly: `300812.SZ` first
appears on its 2020-01-09 listing date, and `300028.SZ` is present through its
inclusive 2020-08-03 out date and absent on 2020-08-04.

## Risk warning and suspension

BaoStock produced 24 bounded `isST=true` intervals. Every start has exactly one
hash-bound CNINFO implementation announcement with an explicit subtype and
effective date: 12 are ordinary `ST` and 12 are `*ST`; unresolved count is zero.
The ordinary control `300029.SZ` begins `ST` on 2020-09-15, and `300795.SZ`
begins `*ST` on 2021-04-28. The official 300795 removal document and the prior
BaoStock daily positive control agree on 2022-04-12; that removal is validation
only and lies outside the authorized date range.

Full-session suspension is authorized only for the proven daily semantics.
Intraday or temporary suspension subtype remains unknown and unauthorized. The
`300198.SZ` 2017-04-20..2017-08-31 control is an exact BaoStock/QMT match:
93/93 dates with sorted compact-date SHA-256
`0dfbbd52889738b0ee0d882199ef87b20b2ef212171bb0c099cd5873aeb211c7`.
The normalized input contains 18,915 full-session suspension rows.

## Gate A

`GATE_A=PASS` for the exact registered artifact. Date-effective GEM identity,
listing, inclusive out-date behavior, non-survivor retention, alias continuity,
ordinary ST, *ST, full-session suspension, hash binding, and fail-closed
unknown/conflict behavior all pass. Missing official evidence, ambiguous alias,
ambiguous subtype, or any source hash mismatch remains a hard failure.

## Gate B

`GATE_B=PASS` for the 180-session `2017-04-12..2017-12-29` warmup:

- QD-001 price: hash-bound; the five null volume/amount rows remain null and are
  not synthetically filled;
- identity: complete date-specific normalized membership, including
  non-survivors;
- state: complete bounded effective state;
- suspension: all five QD-001 null rows for `300372.SZ` are explicit BaoStock
  `tradestatus=0`, blank-volume, blank-amount legitimate suspensions, including
  2017-08-28;
- corporate actions: bounded PIT authorization remains 635/635 exact;
- calendar: exactly 180 QD-003 sessions.

## Authorization boundary and next frontier

The two formerly missing contracts are satisfied free only within this exact
date-, field-, symbol-, strategy-, and hash-bounded ChinNext V1 research scope.
QD-007 remains `DISCOVERY_ONLY` globally. BaoStock is not authorized for other
projects, date ranges, inputs, production, live trading, strict PIT-A, or vendor
revision-lineage claims. Current-survivor fallback remains forbidden.

`SAFE_TO_PREREGISTER_GATE_C=YES`. The next research frontier is a Phase12B4
bounded correctness pilot. This task stops before that pilot and consumes no
2018-2021 strategy performance.
