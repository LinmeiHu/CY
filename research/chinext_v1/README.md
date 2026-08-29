# ChinNext V1 research

## Phase 0 status

This directory is an isolated research scaffold for a future ChiNext single-stock
strategy. Phase 0 contains environment acceptance, a frozen-source inventory, a
design specification, and a gap analysis only. It contains no runnable strategy,
parameter search, performance claim, or full-market backtest.

The frozen source remains read-only:

- Path: `research/supermind_v6/strategy/SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py`
- SHA256: `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`
- Line count: 2677
- Git status: tracked and unmodified at Phase 0 acceptance

The correct source description is **V6 structure + V5-style 20/60/120
cross-sectional RS fallback**. The original V6 `asset_balanced` ranking source is
unavailable; this must not be reconstructed by guesswork.

## Directory contract

- `strategy/`: intentionally empty in Phase 0; no complete strategy is implemented.
- `specs/chinext_v1_design.md`: proposed semantics, causal boundaries, and Phase 1 gates.
- `reports/phase0_gap_analysis.md`: evidence-backed V6-to-ChiNext gap matrix.

All future inputs must comply with `configs/data_asset_registry.json`: preserve
`available_at`, `snapshot_id`, point-in-time identity, `hard_valid`, corporate-action
and execution constraints, and fail closed when required lineage or semantics are
unknown. A current survivor list must never be backfilled into history.

## Phase 1 data foundation

Phase 1 adds only fail-closed data contracts, bounded provider/local-data probes,
and deterministic eligibility tests:

- `specs/chinext_pit_universe_contract.md`
- `scripts/chinext_universe_common.py`
- `scripts/probe_local_chinext_data.py`
- `scripts/probe_qmt_399102.py`
- `scripts/summarize_baostock_pit_probe.py`
- `tests/test_chinext_universe_common.py`
- `reports/phase1_data_foundation.md`

The formal PIT universe remains blocked until a date-effective ChiNext security
master is materialized and activated under the registry. The Phase 1 code returns
an empty/failing eligibility result when any critical identity, listing-age,
risk-warning, suspension, tradability, amount-unit, lineage, or availability fact
is unknown. It never falls back from `399102.SZ` to another index.

## Phase boundary

Phase 0 stops here. The next phase should first materialize and validate the required
point-in-time universe and run narrowly scoped SuperMind API/execution probes. It
should not begin parameter optimization or a full-market backtest.

Phase 1 also stops at the data foundation. It does not implement strategy signals,
portfolio construction, exits, replacement, execution, or returns.
