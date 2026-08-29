# ChinNext V1 Phase 1 data foundation

## Required status summary

```text
PIT_UNIVERSE_STATUS: BLOCKED
LIST_DATE_STATUS: PARTIAL
180_TRADING_DAY_STATUS: VERIFIED
RISK_WARNING_PIT_STATUS: PARTIAL
SUSPENSION_PIT_STATUS: PARTIAL
TURNOVER_UNIT_STATUS: VERIFIED
399102_IDENTITY_STATUS: VERIFIED
399102_HISTORY_STATUS: PARTIAL

CURRENT_SURVIVOR_USED_FOR_HISTORICAL_UNIVERSE: NO
SILENT_399102_FALLBACK: NO

PHASE1_STATUS: COMPLETE_WITH_BLOCKERS
```

The foundation fails closed and is not ready for a complete historical portfolio
backtest. No B60, FULL40, MINVOL, RS, portfolio, T+1 state machine, tail execution,
exit, replacement, return, or optimization code was implemented.

## Frozen inputs

- Repository: `/Users/linmei/Documents/CY-supermind-v6`
- Branch: `research/chinext-v1`
- Phase 1 starting HEAD: `688e3af74e`
- Frozen V6 source SHA256:
  `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`
- Frozen V6 source remained tracked and unmodified.
- Phase 0 README, design, and gap analysis were read before implementation.

## Evidence inventory

### Current master and current survivor

Evidence: `reports/local_data_capability_probe.json`.

- Local security master: 5,891 rows; 1,440 rows currently tagged `SZ/GEM`;
  1,399 are listed.
- Only 2 GEM rows have `list_date`; 0 have `delist_date`.
- The tracked 1,398-name survivor artifact explicitly says
  `NON_PIT_CURRENT_SURVIVOR; most legacy list_date values are absent` and also has
  only 2 known list dates.
- The current list is excluded from historical membership construction.

Conclusion: current metadata can support a coverage diagnostic, not a historical
PIT universe or 180-session eligibility. `LIST_DATE_STATUS` is `PARTIAL` and the
formal universe is `BLOCKED`.

### QD-007 date-specific discovery probe

Evidence: `reports/baostock_qd007_probe_summary.json`; ignored raw payloads remain
under `research/chinext_v1/data/baostock_pit_probe/` and are not Git artifacts.

Three bounded `baostock.query_all_stock(day)` requests succeeded:

| Date | All rows | 300/301 prefix sanity rows | tradeStatus=1 | tradeStatus=0 | Raw file SHA256 |
|---|---:|---:|---:|---:|---|
| 2018-01-02 | 4,042 | 710 | 663 | 47 | `e3623671f2f1488fe6d24e1251d231ea15c5eb095271d2ff4573e5aecdc9250a` |
| 2020-08-24 | 4,515 | 851 | 847 | 4 | `4867294d9f5257ed2ea4da4858ff4158fe4b03bbdf9184ce90483a8a1717cae5` |
| 2026-08-12 | 7,340 | 1,401 | 1,400 | 1 | `1ecd00c3139ea84e76cdd5e8f1d3dde279192fd5a6d5b5a9c28d0e397e55c42b` |

This proves a date-parameterized discovery capability and an observed
`tradeStatus` field. It does not close the gate:

- Registry asset QD-007 remains `DISCOVERY_ONLY / CANDIDATE_NOT_MATERIALIZED` and
  explicitly blocks universe construction, survivorship claims, signals, and
  backtests.
- Only three dates were probed.
- Returned fields are `code`, `tradeStatus`, and `code_name`; there is no list
  date, delist date, or explicit board field.
- Prefix counts are sanity diagnostics only.
- `code_name` was not used to infer ST or risk-warning history.

### CY-006 and QD-002 daily state capability

Evidence: `reports/local_data_capability_probe.json`, registry QD-002/CY-006, and
the bounded 2020 CY-006 query.

CY-006 is a registered PIT-B daily table for 2018-01-01..2026-08-12. Its schema
contains daily `trade_status`, `is_st`, `buy_blocked_open`, `sell_blocked_open`,
limits, amount, `available_at`, `snapshot_id`, `historical_identity_valid`, and
`hard_valid`.

For 2020 rows whose codes pass the 300/301 sanity filter:

- 201,867 rows / 897 symbols;
- 258 `is_st=true` rows;
- 1,043 `trade_status != 1` rows;
- 1,884 buy-blocked-open and 2,200 sell-blocked-open rows;
- 0 missing `available_at` rows;
- 8,746 hard-invalid rows remain explicit;
- 0 historical-identity-invalid rows in this bounded partition.

The source path maps BaoStock daily `isST` to `is_st`. No inspected contract proves
that this Boolean includes every required `*ST` or other risk-warning subtype.
Therefore it cannot be silently mapped to a complete canonical
`risk_warning=false`; unknown categories fail closed. `RISK_WARNING_PIT_STATUS` is
`PARTIAL`.

Daily suspension/state facts are physically present and date-varying, but exact
side-specific exchange tradability and future execution-window semantics are not
fully proven by an OHLCV row or `tradeStatus` alone. The Phase 1 contract separates
`OBSERVED_DATA_AVAILABILITY` from `EXCHANGE_TRADABILITY_FACT` and requires exact
false/true values. `SUSPENSION_PIT_STATUS` is `PARTIAL`.

### Turnover unit and window

The accepted canonical field is `amount_cny`; ambiguous `turnover` and
`turnover_rate` are rejected. In the bounded CY-006 2020 ChiNext sample, median
`amount / (close * volume)` is `1.0000055353303303`, consistent with volume in
shares and amount in CNY. Registered related A-share market assets also state
volume in shares and amount in CNY.

The frozen Phase 1 window is the last 20 explicit exchange sessions ending on the
completed signal session `t`, inclusive. All 20 facts need `amount_unit=CNY`, known
lineage, causal availability, and hard validity. Exactly CNY 100m passes; below,
NaN, unknown unit, or missing history fails. `TURNOVER_UNIT_STATUS` is `VERIFIED`
for this canonical CY-006 adapter contract.

### Listing age

Contract: `specs/chinext_pit_universe_contract.md`.

```text
first_session = first explicit exchange session >= list_date
listed_trading_days(t) = inclusive count from first_session through t
pass when listed_trading_days(t) >= 180
```

Signal date `t` counts. The 179th session fails and the 180th passes. The function
consumes an explicit trading calendar and never uses calendar-day age. Logic and
boundaries are covered by deterministic tests, so `180_TRADING_DAY_STATUS` is
`VERIFIED`; real-universe use remains blocked by list-date coverage.

### 399102.SZ

Evidence: `reports/qmt_399102_probe.json` generated by the bounded single-symbol
QMT script `scripts/probe_qmt_399102.py`.

QMT instrument detail returned:

```text
ExchangeID: SZ
ExchangeCode: 399102
InstrumentID: 399102
InstrumentName: 创业板综
UniCode: 399102
```

`399102_IDENTITY_STATUS` is `VERIFIED` for the QMT provider identity.

The single-index daily request returned 3,946 unique rows from 2010-06-01 through
2026-08-28, covering the planned CY-006 research interval. Canonical response hash:
`c9db4e544e4494749483798c4a3f55fb9163749591e29b859fb462c89b81a131`.
Raw versus QMT `front` open/high/low/close mismatches are all zero, supporting use
of unadjusted index levels rather than an equity adjustment model.

History is still `PARTIAL` because:

- QD-003 does not contain `399102` and no registry asset currently activates this
  new extraction;
- the provider response has no row-level `available_at` field;
- the full extracted series was not added to Git; only identity, coverage, hash,
  columns, and four sample rows were frozen in the probe summary.

Later materialization must freeze the daily partition and manifest, attach a
conservative completed-bar availability, and register the asset. The exact anchor
loader raises when `399102.SZ` is missing and never tries `399006`, `000852`, or
another index. `SILENT_399102_FALLBACK` is `NO`.

## Implementation

`scripts/chinext_universe_common.py` contains only data-foundation primitives:

- typed static/date-effective security facts and daily PIT facts;
- timezone-aware availability and nonempty lineage gates;
- board membership from an explicit `CHINEXT` fact, never prefix inference;
- inclusive exchange-session listing age;
- risk-warning, suspension and buy-tradability fail-closed gates;
- completed-session 20-day CNY amount gate;
- current-survivor historical-backfill rejection;
- exact `399102.SZ` lookup with no fallback.

No builder claims to produce an actual PIT universe from current inputs. With the
current evidence, missing master/risk facts yield explicit ineligible reason codes,
which is the required fail-closed behavior.

## Deterministic validation

Command:

```bash
pytest -q research/chinext_v1/tests/test_chinext_universe_common.py
```

Result:

```text
15 passed in 0.01s
```

Covered cases:

1. future-listed security excluded;
2. 179 listed sessions fail;
3. exactly 180 sessions pass;
4. membership-end/delist-normalized date excluded;
5. risk-warning true excluded;
6. suspended and non-tradable excluded;
7. turnover20 exactly CNY 100m passes;
8. below threshold fails;
9. NaN fails;
10. insufficient 20-session history fails;
11. unknown risk/suspension/tradability fails closed;
12. current survivor cannot backfill history;
13. missing `399102.SZ` does not fall back even when other indices exist;
14. exact `399102.SZ` is accepted.

## Phase 1 decision

`PHASE1_STATUS` is `COMPLETE_WITH_BLOCKERS`.

Verified foundation:

- frozen-source integrity;
- inclusive 180-exchange-session algorithm and boundary tests;
- CNY amount semantics and 20-completed-session window;
- QMT identity of `399102.SZ`;
- deterministic fail-closed behavior, current-survivor exclusion, and no anchor
  fallback.

Partial foundation:

- static listing metadata coverage;
- daily ST/risk-warning taxonomy;
- suspension and side-specific tradability semantics;
- QMT anchor history extraction/availability/registration.

Blocking facts:

1. No materialized and activated date-effective ChiNext board/list/delist master.
2. Only 2 current GEM rows have list dates; the current survivor artifact is not
   PIT.
3. QD-007 remains discovery-only and has not been audited/materialized for every
   required session.
4. `is_st` completeness for `*ST` and all required risk-warning categories is not
   proven.
5. `399102.SZ` history is not yet a registered immutable input with row-level
   availability.

Do not proceed to a complete historical portfolio backtest while these blockers
remain.

## Recommended Phase 2 scope

1. Materialize complete date-effective security snapshots outside Git, reconcile
   official listing/delisting/board facts, freeze hashes and revisions, validate
   every required session, and promote through a new registry revision.
2. Establish a complete PIT mapping for ST, `*ST`, and other risk-warning states;
   retain unknown values as hard failures.
3. Materialize `399102.SZ` daily levels into an immutable partition/manifest,
   normalize completed-bar `available_at`, validate calendar coverage, and register
   it without fallback.
4. Re-run only universe/anchor validation on tiny date/symbol samples. Strategy,
   portfolio, T+1 execution, exits, replacement, optimization, and full-market
   return backtests remain outside that data-gate step.
