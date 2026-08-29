# ChinNext V1 research

> **CURRENT SURVIVOR UNIVERSE / NOT POINT-IN-TIME / SURVIVORSHIP BIASED /
> NOT VALID FOR FINAL PERFORMANCE CLAIMS** applies to the exploratory smoke
> baseline described below. It does not change the separate Phase 1 PIT contract.

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

## Exploratory survivor-biased baseline

The explicitly authorized `EXPLORATORY_SURVIVOR_BIASED` path is implemented as
an independent research strategy and deterministic small-sample replay:

- `strategy/chinext_v1_exploratory.py`: causal B60/FULL40/MINVOL/breakout-volume,
  20/60/120 cross-sectional RS, MA30 x 2 exit, fixed 10% member targets,
  no-replacement membership and next-open/T+1 primitives.
- `scripts/run_chinext_v1_smoke.py`: reads existing Mac CY-006 stock data and the
  existing quant exchange calendar, selects 50 current survivors without looking
  at outcome returns, and runs only the 2024-01-02..2025-12-31 smoke replay.
- `scripts/export_qmt_399102_smoke.py`: bounded one-symbol freezer for the exact
  verified `399102.SZ` QMT anchor; it is not a stock-data downloader.
- `tests/test_chinext_v1_exploratory.py`: targeted semantic and execution tests.
- `reports/chinext_v1_smoke.md` and `reports/chinext_v1_smoke_summary.json`: the
  labeled human- and machine-readable results. Full event/execution/NAV ledgers
  remain under the Git-ignored `output/chinext_v1_smoke/` directory.

This exploratory route does not modify, bypass, or claim to satisfy the canonical
PIT universe contract. Complete historical risk-warning coverage remains unknown.
The execution limit model is `PARTIAL`: known CY-006 open-limit/trade-state fields
are enforced, while order-book queue and impact are not modeled.

## Full current-survivor replay

`scripts/run_chinext_v1_full_survivor.py` runs the same frozen configuration over
every symbol in the current-survivor manifest for exactly 2024-01-02 through
2025-12-31. Daily RS uses the full basic-eligible cross section. The human report
is `reports/chinext_v1_full_survivor.md`; the machine summary is
`reports/chinext_v1_full_survivor_summary.json`; large ledgers remain Git-ignored.

This expansion is still **NON-PIT and SURVIVORSHIP BIASED**. Its purpose is only to
judge whether a separately authorized PIT validation is worth undertaking. It does
not change B60, FULL40, MINVOL, RS weights, MA30, market gate, portfolio sizing,
replacement, T+1, execution timing, or any other strategy parameter.

## Phase boundary

Phase 0 stops here. The next phase should first materialize and validate the required
point-in-time universe and run narrowly scoped SuperMind API/execution probes. It
should not begin parameter optimization or a full-market backtest.

Phase 1 also stops at the data foundation. It does not implement strategy signals,
portfolio construction, exits, replacement, execution, or returns.

The later exploratory baseline is a separate, explicitly survivor-biased research
artifact. It stops after the deterministic 50-stock smoke run. It performs no
parameter sweep and no full-current-universe or formal PIT-universe backtest.
