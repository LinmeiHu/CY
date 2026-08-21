# Operator runbook

0. Validate `configs/data_asset_registry.json`. An unregistered asset, missing path, changed hash, or global `backtest_authorized=false` blocks research execution.
1. Build a PIT store only from an explicitly activated immutable input snapshot made exclusively from registered `RESEARCH_CONDITIONAL` assets. Reject timestamp conflicts, unknown float, invalid OHLC, unknown rules, and missing cross-table joins.
2. Run research with a named run ID only after the registry and data-quality gates authorize it. The final holdout stays locked unless a logged access event explicitly taints it.
3. Promote only when tests, lint, typing, deterministic replay, cost stress, and ablation reports pass.
4. Paper mode creates versioned plans and simulated orders. It cannot send broker traffic.
5. Shadow mode compares intended state with an externally supplied account snapshot. Any mismatch raises the kill switch.
6. On data/rule ambiguity, blocked exits, event-store hash mismatch, registry mismatch, or reconciliation failure: stop new risk, preserve pending state, record the incident, and roll back to the last signed release/snapshot.

Never repair performance by editing an event log, deleting a failed experiment, changing a plan in place, assuming a limit-board exit, or relabeling a failed short-horizon trade as value investing.

## Data registry gate

```bash
.venv/bin/python scripts/validate_data_registry.py
```

The authoritative machine registry is `configs/data_asset_registry.json`; `docs/data-asset-registry.md` is its human-readable summary. Passing the validator proves only that the declared baseline is internally consistent and that frozen evidence has not changed. It does not activate conditional data and does not override `global_gate.backtest_authorized`.

When a new source or snapshot is found, first perform a bounded read-only probe. Then archive immutable originals or responses, allocate a `snapshot_id`, preserve `available_at/source/revision_id`, record units and coverage, run coverage/duplicate/time-travel/consistency audits, and append the asset plus evidence to the registry. Re-downloading, moving, changing units, changing source priority, or replacing one vendor with another creates a new registry revision; it is never a silent runtime fallback.

`QA_ONLY`, `DISCOVERY_ONLY`, `DEMO_ONLY`, `GENERATED_OUTPUT`, and `UNAVAILABLE` entries cannot feed states, signals, sizing, execution, or performance reports. A `RESEARCH_CONDITIONAL` entry can do so only after all listed activation gates and combination-level D1-Q1 gates pass. Strict PIT output additionally requires every necessary input to be grade A.

## Normalized input contract

- Daily bars require `symbol,trade_date,open,high,low,close,volume,amount,free_float_shares,available_at`; suspension, ST and explicit limits are optional but recommended.
- Industry memberships require `symbol,industry,effective_from,available_at`; `effective_to,source,snapshot_id,revision_id` are optional only because the importer can attach immutable file lineage.
- Fundamentals require `symbol,period_end,available_at` plus any available state inputs: `revenue_growth,profit_growth,roe,operating_cashflow_to_profit,debt_ratio,valuation_percentile,earnings_revision,investment_growth,capital_return,audit_or_going_concern_risk`. `event_time,effective_from,source,snapshot_id,revision_id` should be supplied by production adapters.
- Corporate actions require a stable `action_id`, economic `ex_date`, event/publication timestamps, and action-specific values. Actions not known by the ex-date are rejected instead of retroactively altering chip cost.
- Timestamps must include a UTC offset. The importer normalizes fundamental disclosure timestamps to UTC and keeps file SHA-256 digests in the ingest manifest.

## Activated PIT-B reproducible research sequence

The R2 manifest is authorized for B-grade causal research over its declared date range. Authorization is exact: a different manifest, source digest, registry digest, purpose, or date range must pass activation again. Strict PIT-A remains unavailable.

The staged validation order is one symbol for 3–6 months, ten symbols for 1–2 years, all-market short validation, then one frozen 2020–2026 final run. Do not rerun the final holdout merely to tune the strategy. The completed final invocation was:

```bash
.venv/bin/cyq-game backtest \
  --config configs/research_pit_b_final.yaml \
  --registry configs/data_asset_registry.json \
  --input-manifest data/input_snapshots/CYQ-PIT-B-DAILY-2018-2026-20260820-R2.json \
  --history-start 2018-01-02 \
  --start 2020-01-02 \
  --end 2026-08-12 \
  --run-id pitb-final-all-20200102-20260812-u3 \
  --walk-forward \
  --access-final-holdout

.venv/bin/cyq-game replay \
  --config configs/research_pit_b_final.yaml \
  --run-id pitb-final-all-20200102-20260812-u3 \
  --deterministic
```

Review `summary.json`, `decisions.jsonl`, `walk_forward.json`, `research_diagnostics.json`, `events.jsonl`, `manifest.json`, and `replay_report.json` together. The final run is deliberately marked `holdout_tainted=true` because final holdout access was explicitly logged after the configuration was frozen. This is acceptable for one final evaluation, but it forbids treating later tuning against that period as unseen validation.

The completed result is not promotable: total return, Sharpe, Sortino, Calmar, and profit factor fail the economic gate. Robustness expansion was therefore stopped; a more expensive matrix cannot rescue a strategy that already fails its primary frozen evaluation. Full evidence is in [`pit-b-final-validation.md`](pit-b-final-validation.md).

## Shadow controls

Run `scripts/reconcile_shadow.py` only with `mode: shadow` and an externally produced, timestamped account-snapshot JSON. A mismatch exits non-zero and persists the kill switch. Inspect with `cyq-game kill-switch-status`; reset requires an approval ID and reason through `cyq-game kill-switch-reset`. Neither command has a path to a live broker.
