# Formation-depth x CHINEXT V1 habitat data contract

Frozen before the habitat join or any strategy association estimate.

## Immutable inputs

- Formation-depth state: exact MKT-BREAKOUT-DIFF-001 panel and supported
  MKT-BREAKOUT-ECON-001 result.
- Strategy process/outcomes: exact HAB-CHX-001 panel/result. Its 2018--2023
  CHINEXT event ledgers and completed cycles are already consumed exploratory
  evidence; no source ledger is reopened.
- Volatility control: exact MKT-VOL-001 panel/result.
- Trend and discovery controls: exact columns already bound into HAB-CHX-001.

Changed hashes, duplicate keys, sample counts, state view/denominator, timestamps,
execution ordering, or outcome lineage fail closed. No raw daily/minute partition,
alternate strategy replay, post-2023 data, QD-004, CY-008, or CY-011 is read.

## Exact join

Join `trade_date` from every HAB-CHX-001 row to the unique
CHINEXT_BOARD/ALL_STATUS formation-depth state. Join the same date/view/denominator
to `realized_volatility_median20`. Require all 2,436 HAB rows and exact inherited
sample counts: 1,337 daily, 819 evaluated events, and 280 completed cycles.

All raw formation-depth values must be present. Causal PIT missingness before the
504-observation warm-up is preserved; expected PIT counts are 914 daily, 645 event,
and 211 cycle rows. No interpolation, expanding-rank substitution, year rank,
relative-coordinate rescue, or row deletion is allowed.

The signal state is the completed-close state at t. `entry_execution_date` for
every cycle remains strictly later than t. Outcome fields may be read only after
this contract is frozen and never become predictors.

## Endpoint filters

- Daily endpoints use exactly `sample_type == DAILY_PROCESS`.
- `admissible_candidate` uses all `EVALUATED_EVENT` rows.
- `selected_admission` uses evaluated rows with `admissible_candidate == true`.
- Cycle endpoints use exactly `COMPLETED_CYCLE`.
- `conversion20` uses completed cycles with `opportunity20 == true`.

Missing endpoint values outside their specified sample are structural. Inside a
specified sample they fail closed. Binary fields must be exactly 0/1; continuous
fields must be finite. No winsorization, clipping, imputation, class weighting, or
synthetic zero is allowed.

## Evidence and output boundary

Cluster bootstrap seeds are SHA-256-derived from experiment/endpoint/replicate.
Repeated date draws repeat the whole date cluster. Raw absolute associations use
all available 2018--2023 rows; causal PIT sensitivity uses only naturally
available rows. Controls must be finite in the tested row and may not be deleted.

Durable outputs contain the joined panel, endpoint audit, bootstrap summary,
result, and report. They contain no fitted trade score, recommendation, allocation,
or production artifact. Two executions must be byte-identical. One process, 3 GiB
RSS, 8 GiB system headroom, five-minute wall clock, and 100 MiB durable output are
hard ceilings.

Passing establishes only an exploratory pre-2024 strategy-habitat association in
already-consumed evidence. It does not establish causality, confirmation, a
tradable state boundary, improved V1 performance, or authorization to modify the
strategy.
