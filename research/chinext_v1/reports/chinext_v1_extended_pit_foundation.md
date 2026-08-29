# ChinNext V1 — extended PIT foundation current-HEAD adjudication

## Outcome

This is an outcome-blind causal-input assessment. It created no universe, daily
state materialization, pilot, strategy signal, trade, NAV, or performance metric.

- `GATE_A=BLOCKED_EXTERNAL_DATA`
- `GATE_B=BLOCKED_EXTERNAL_DATA`
- `GATE_C=NOT_AUTHORIZED`
- `GATE_D=NOT_AUTHORIZED`
- `SAFE_TO_RUN_EXTENDED_HISTORY_STRATEGY_REPLAY=NO`

The result is not a generic `DATA_GOVERNANCE_INCOMPLETE` finding. The remaining
work is reduced to the two exact acquisition contracts frozen in
`chinext_v1_extended_pit_foundation_summary.json`.

## Current-HEAD reconciliation

- Starting HEAD: `396d20bfe98b74aa2af286c8e0ae64fe44c8f503`
- Frozen strategy SHA-256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Corporate-action research and implementation closure: `RESOLVED`
- QD-010/CY-006 reconciliation: `635/635` exact event-ID matches, `0` unmatched
- QD-010 authorization: `BOUNDED_PIT_AUTHORIZED`; its
  `revision_history_complete=false` limitation is retained and is not promoted to
  strict PIT-A.

`chinext_v1_phase12b3_warmup_overlap.json` and the corresponding corporate-action
blocker in `chinext_v1_phase12b3_input_activation_summary.json` are stale only for
the old 635/634 finding. The superseding authority is
`chinext_v1_corporate_action_adjudication.md`. The historical-state warnings in
the older Phase12B3 artifacts remain valid.

## Gate A — source adjudication

| Source | What current evidence proves | Authorization boundary | Why it cannot close Gate A |
|---|---|---|---|
| QD-002 | Hash-bound daily `trade_status`, generic `is_st`, limits and blocked-open state from 2006-04-20; physical rows retain later-ended symbols | `RESEARCH_CONDITIONAL`, not a standalone universe | No board assertion, alias chain or official list/out boundary; `is_st` does not prove ST versus *ST taxonomy; suspension subtype semantics are incomplete |
| CY-027 | Exact hash-bound 2024-2025 artifact with 1,440 master rows, 1,404 membership symbols, 41 `out_date` rows and five-date reconciliation | Only `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1` | Builder starts from a current GEM master/current BaoStock basic snapshot; registry explicitly forbids other ranges and historical backfill |
| QD-007 | BaoStock `code`, `tradeStatus`, `code_name` discovery captures | `DISCOVERY_ONLY` | No 2018-2021 materialization, no board field, no supplier revision chain; 2017 capture begins 2017-07-03 and records 68 failed dates |

All inspected component hashes match their current registered/frozen values. That
does not create an authorized composite historical state.

### GEM identity, listing and non-survivors

The canonical contract requires a time-qualified `board=CHINEXT` assertion.
Ticker prefixes are sanity checks only and cannot create membership.

The current local master contains both `300132` and `302132` as current GEM
symbols. Existing repository identity logic rejects `302132.SZ` before
2025-02-17. This is a direct counterexample to projecting the current master into
2018-2021. It also explains why the resolved 2018 corporate-action row carried
the later `302132` alias without making that alias historically eligible.

QD-002 physically retains examples whose final row precedes target end, including
`300362` (2021-08-30), `300431` (2020-11-10), and `300028` (2020-08-03). These are
useful non-survivor diagnostics, but a first/last price or state observation is not
an official listing/delisting boundary and cannot establish historical GEM
membership.

Therefore:

- `GEM_IDENTITY_STATUS=BLOCKED_NO_AUTHORIZED_DATE_EFFECTIVE_SOURCE`
- `LISTING_STATUS=BLOCKED_NO_AUTHORIZED_LISTING_BOUNDARY_AND_ALIAS_CHAIN`
- `DELISTING_STATUS=BLOCKED_NO_AUTHORIZED_END_BOUNDARY_SEMANTICS`
- `NON_SURVIVOR_STATUS=PHYSICAL_ROWS_OBSERVED_NOT_AUTHORIZED_AS_MEMBERSHIP`

### ST, *ST and suspension

The source path maps BaoStock daily `isST` to QD-002 `is_st`. Prefix-screened
diagnostics contain 258 true rows in 2020 and 4,204 in 2021; examples begin on
2020-09-15 for `300029`, `300367`, and `300446`. No inspected contract proves
that this boolean distinguishes or completely covers ST, *ST, and every excluded
risk-warning category. Canonical `is_star_st` therefore cannot be populated.

QD-002 also retains many `trade_status=0` observations, including 7,084 rows in
2018. These prove provider daily-state retention, not a complete distinction among
full-day suspension, intraday halt, temporary suspension, and unsupported states.
A missing bar or zero volume remains forbidden as a suspension inference.

Therefore:

- `ST_STATUS=PARTIAL_GENERIC_IS_ST_BOOLEAN_ONLY`
- `STAR_ST_STATUS=BLOCKED_NOT_DISTINGUISHED`
- `SUSPENSION_STATUS=PARTIAL_DAILY_TRADE_STATUS_ONLY`

No minimal adapter can manufacture the missing source semantics, so no historical
state builder or materialization is justified at this gate.

## Gate B — exact 2017 warmup

The frozen strategy requires 180 completed observations. This dominates the other
windows: contiguous history 121, B60 61, FULL40 40, MINVOL 31,
breakout-volume 21, RS120 120, and the MA windows.

- Earliest formal decision: `2018-01-02`
- Calendar sessions required: `180`
- Required warmup: `2017-04-12 .. 2017-12-29`
- Calendar status: `PASS` (`180/180` exchange sessions)
- QD-010 corporate-action status: `PASS_BOUNDED_PIT_AUTHORIZED`
- QD-001 price status: `PARTIAL_SOURCE_READY`; 120,642 prefix-screened rows are
  present and hash-bound, but five `300372` rows have null volume/amount and must
  fail closed, while the authorized identity denominator is absent
- Historical state status: `BLOCKED_EXTERNAL_DATA`
- Identity/non-survivor status: `BLOCKED_EXTERNAL_DATA`

The price and state counts above are diagnostics only. They do not use ticker
prefixes as historical membership. Because complete identity/state compatibility
is missing, `GATE_B=BLOCKED_EXTERNAL_DATA`.

## Dependent gates

Gate C requires Gate A and Gate B to pass. No pilot spec was created and no pilot
was run. Gate D requires Gate C to pass; all requested large-validation metrics
are `NOT_RUN`. This is a prerequisite stop, not a pilot failure.

## Exact missing-data contracts

### 1. Historical identity, list/out and aliases

Acquire one authorized historical security master/event feed or complete dated
exchange snapshots covering `2017-04-12 .. 2021-12-31`. It must contain stable
security identity, symbol and alias effective intervals, exchange, board, listing
boundary, delisting/membership-end boundary with explicit inclusivity, source
record identity, known/snapshot time, and revision/snapshot identity for every
security ever on GEM in the interval, including non-survivors.

Acceptance requires complete 180-session warmup and 973-session target coverage,
no unexplained snapshot gaps, deterministic hash-bound rebuilds, exact boundary
tests, and explicit resolution of the `302132.SZ` pre-2025 alias case. Current
survivor and ticker-prefix fallbacks must remain disabled.

### 2. Risk warning and suspension semantics

Acquire an authorized historical risk-warning/tradability event or daily-state
feed plus its authoritative codebook for the same date/symbol scope. It must
distinguish normal, ST, *ST and other required warning categories; preserve
announcement/known/effective/removal boundaries; and classify source-supported
suspension states without converting unsupported states to false.

Acceptance requires date-boundary tests for normal-to-ST, ST-to-*ST and removal
where present; distinct canonical ST/*ST values; documented suspension semantics;
one-to-one joining to the authorized identity denominator; future-visibility,
unknown, duplicate, conflict and hash-drift rejection. QD-002 may be retained as a
supplemental cross-check only after equivalence is proved.

No external provider is selected or implicitly authorized by this report.

## Next direction

Acquire and boundedly register only the two contracted causal inputs. Then reuse
the existing minimal universe/state contract and test patterns to close Gate A and
Gate B. A preregistered correctness pilot becomes permissible only after both
gates pass; formal 2018-2021 strategy performance remains unseen.
