# Formation-depth propagation response data contract

Frozen with the propagation topology map before constructing or inspecting any
crossing/noncrossing response. This contract reuses the accepted pre-2024 CY-006
action-coordinate response domain and changes only the retained t membership
label.

## Immutable inputs and lineage

- exact MKT-BREAKOUT-DIFF-001 predictor panel/result;
- exact MKT-BREAKOUT-ECON-DATA-001 panel/result for broad-domain reproduction;
- registered CY-006 daily PIT-B source and the same six hashed 2018--2023
  partitions;
- exact MKT-BREAKOUT-DIFF-DATA-001 supported-action coordinate builder;
- exact formation-depth propagation map.

Changed hashes, registry activation, source keys, partition identity, source date
range, snapshot, or accepted coordinate runner fail closed. There is no file
discovery, alternate source, adjusted vendor field, raw-price fallback, QD-004,
CY-008, post-2023 partition, strategy artifact, or CY-011 access.

## Cohort algebra

For each event date t, market view v, and denominator d, let `A_t` be the exact L20
anchor cohort from MKT-BREAKOUT-DIFF-001 and let `I_t` be its exact valid complete-
five-session response subset from MKT-BREAKOUT-ECON-DATA-001.

Define membership from information at t only:

- `X_t = {i in A_t: cross20_i,t is true}`;
- `N_t = A_t \ X_t`;
- `X*_t = I_t intersection X_t`;
- `N*_t = I_t intersection N_t`.

The following integer identities are hard requirements for every cell:

- `|X_t| + |N_t| = |A_t|`;
- `|X*_t| + |N*_t| = |I_t|`;
- the recomputed `|X_t|` equals exact predictor `crossing_count20`;
- the recomputed `|A_t|` equals exact predictor `eligible_count20`;
- no symbol belongs to both arms.

No normalization, imputation, future membership, future ST selection, security
replacement, propensity matching, rounding, clipping, or tolerance may repair a
failure.

## Response coordinate

For every member of `I_t`, reproduce the accepted continuous coordinate close,
five consecutive future supported-action steps, future coordinate closes, and
mapped lows with `C * (raw_low / raw_close)`, evaluating the ratio first. Security
terminal return and adverse excursion are unchanged from the accepted contract.

For each arm and h in exactly {1,3,5}, retain count, deterministic sum, and
equal-weight mean for terminal log return and adverse log excursion. The sums are
audit ledgers; no capital weighting or interpretation as a tradable portfolio is
allowed.

The original broad count and all six broad means must reproduce the immutable
MKT-BREAKOUT-ECON-DATA-001 panel exactly when computed by its original grouping
path. Subcohort counts must conserve exactly. Subcohort sums and means must be
finite and internally satisfy the same deterministic operation order on two full
runs. No floating tolerance is authorized as a broad-reproduction substitute.

## Data-adequacy gates

The broad domain retains all accepted gates: 11,296 complete cells, at least 95%
anchor retention, original view floors, at least 150 dates per view/denominator/
year, and no response after 2023-12-29.

A topology-complete cell additionally requires:

- crossing response retention >=0.90;
- crossing response count at least 15/5/7/2 for ALL_A/SH_A/SZ_A/CHINEXT_BOARD;
- noncrossing response count at least 800/300/300/100 for those views;
- both arm metrics finite at all three horizons.

Every view/denominator/year must retain at least 150 topology-complete dates. The
later economic join must have at least 6,000 complete five-control rows and at
least 750 per cell. These are support gates, not post-result filters. A failure
closes this exact topology experiment without changing the arm definition or
floor.

## Outcome-blind construction audit

The data experiment may construct the membership-resolved panel and report only:

- source, key, PIT, snapshot, clock, and action-coordinate audits;
- exact arm/exhaustion counts and retention;
- broad-response exact reproduction;
- topology-complete date support by view/denominator/year;
- ten hash-selected scalar cases, five from each arm, reconstructing the fixed
  coordinate and membership fields without the aggregate helper;
- response values only in the durable panel.

It may not calculate a state/arm response association, high/low contrast, partial
correlation, paired topology effect, favorable channel, classification, strategy
outcome, or trading rule. The runner must not print response summaries.

## Resources and determinism

Use one Python process, one DuckDB thread, 1.5 GiB DuckDB memory, 10 GiB disposable
spill, 3 GiB process RSS, 8 GiB system headroom, 20 GiB compressed reads, a
20-minute wall clock, and 100 MiB durable output. No security-level durable table
or raw copy is allowed. Runtime and volatile host measurements are not serialized.
Two full runs must reproduce byte-identical panel, count audit, scalar audit,
result, and report.

Passing establishes only a valid membership-resolved market response domain. It
does not establish localization, propagation, reversal, prediction, causality,
habitat, execution, payoff, or strategy usefulness.
