"""Materialize the complete, causal MARKUP_RETEST lifecycle event stream.

The generator is intentionally label-blind and capacity-blind.  It processes
the warm-up rows in symbol/date order, emits every threshold-qualified signal,
and marks whether each event belongs to the evaluation interval.  Portfolio
ranking, Top-N selection and labels are not accepted by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.chip.ensemble_v2 import AnchorRetentionEstimate
from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION
from cyq_game.chip.price_coordinate import parse_action_ids
from cyq_game.chip.state_v2 import SellerModel
from cyq_game.strategy.chip_lineage import StreamingLineageSession
from cyq_game.strategy.markup_retest import (
    AnchorRetentionResolver,
    ChipMassProfile,
    LifecycleMachine,
    LifecycleMemory,
    LifecycleObservation,
    MarkupRetestConfig,
    StrategyParameters,
    StrategySignal,
    StrategyStage,
    assert_no_label_access,
    load_passing_frozen_parameters,
    verify_registered_asset_inventory,
)
from cyq_game.strategy.panel import PanelBuildResult
from cyq_game.strategy.semantic_contract import (
    SIGNAL_SCHEMA_VERSION,
    require_active_semantic_epoch,
    semantic_fingerprint_fields,
)

CN_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class GeneratedSignalEvents:
    signals: tuple[dict[str, Any], ...]
    events: tuple[dict[str, Any], ...]
    input_rows: int
    evaluation_rows: int
    evaluation_signal_rows: int


@dataclass(frozen=True)
class SignalBuildResult:
    stage: str
    status: str
    path: Path
    manifest_path: Path
    rows: int
    evaluation_rows: int
    signal_rows: int
    evaluation_signal_rows: int
    event_rows: int
    symbols: int
    config_sha256: str
    panel_snapshot_id: str
    signal_snapshot_id: str
    parameter_id: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


@dataclass(frozen=True)
class SignalShardMetrics:
    input_rows: int
    evaluation_rows: int
    signal_rows: int
    evaluation_signal_rows: int
    event_rows: int
    signal_symbols: tuple[str, ...]
    files: tuple[str, ...]


def signal_path(
    config: MarkupRetestConfig,
    stage: StrategyStage | str,
    parameters: StrategyParameters | None = None,
) -> Path:
    boundary = config.stage(stage)
    frozen = (
        load_passing_frozen_parameters(config)
        if boundary.name == StrategyStage.RESEALED
        else None
    )
    selected = parameters or frozen or config.parameters
    if frozen is not None and selected != frozen:
        raise ValueError("resealed signals require exactly the frozen economic parameters")
    return (
        config.outputs.signal_root
        / boundary.name.value
        / config.sha256[:12]
        / selected.parameter_id
    )


def generate_signal_events(
    records: Iterable[Mapping[str, object]],
    config: MarkupRetestConfig,
    *,
    parameters: StrategyParameters | None = None,
    panel_snapshot_id: str = "panel-in-memory",
    anchor_retention_resolver: AnchorRetentionResolver | None = None,
) -> GeneratedSignalEvents:
    """Advance the lifecycle over already ordered predictor-only records.

    The function is useful both for small deterministic tests and the streamed
    parquet materializer.  Records must be strictly ordered by symbol/date and
    unique on that key; accepting unsorted input could silently corrupt state.
    """

    selected = parameters or config.parameters
    machine = LifecycleMachine(
        config,
        selected,
        anchor_retention_resolver=anchor_retention_resolver,
    )
    signals: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    input_rows = 0
    evaluation_rows = 0
    evaluation_signal_rows = 0
    symbol: str | None = None
    previous_key: tuple[str, date] | None = None
    memory = LifecycleMemory()
    trading_index = 0

    for raw_record in records:
        record = dict(raw_record)
        assert_no_label_access(record)
        row_symbol = _required_text(record, "symbol")
        trade_date = _as_date(record.get("trade_date"), field="trade_date")
        key = (row_symbol, trade_date)
        if previous_key is not None and key <= previous_key:
            raise ValueError(
                "signal input must be unique and ordered by symbol/trade_date: "
                f"previous={previous_key}, current={key}"
            )
        previous_key = key
        if symbol != row_symbol:
            if symbol is not None and isinstance(
                anchor_retention_resolver, StreamingLineageSession
            ):
                anchor_retention_resolver.release_symbol(symbol)
            symbol = row_symbol
            memory = LifecycleMemory()
            trading_index = 0

        observation = observation_from_record(record, config, panel_snapshot_id)
        is_evaluation = _as_bool(record.get("is_evaluation_row"))
        previous_state = memory.state
        previous_distribution_days = memory.distribution_days
        result = machine.advance(memory, observation, trading_index=trading_index)
        input_rows += 1
        evaluation_rows += int(is_evaluation)

        if result.memory.state != previous_state:
            events.append(
                _event_record(
                    event_type="STATE_TRANSITION",
                    observation=observation,
                    parameter_id=selected.parameter_id,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    from_state=previous_state.value,
                    to_state=result.memory.state.value,
                    active_signal_id=result.memory.active_signal_id,
                )
            )
        if result.signal is not None:
            serialized = serialize_signal(
                result.signal,
                panel_snapshot_id=panel_snapshot_id,
                is_evaluation=is_evaluation,
            )
            signals.append(serialized)
            evaluation_signal_rows += int(is_evaluation)
            events.append(
                _event_record(
                    event_type="SIGNAL_CREATED",
                    observation=observation,
                    parameter_id=selected.parameter_id,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    from_state=previous_state.value,
                    to_state=result.memory.state.value,
                    active_signal_id=result.signal.signal_id,
                )
            )
        if result.soft_exit_cancelled:
            if previous_distribution_days != 1:
                raise RuntimeError("soft-exit cancellation lost its first-day evidence")
            events.append(
                _event_record(
                    event_type="SOFT_EXIT_CANCELLED",
                    observation=observation,
                    parameter_id=selected.parameter_id,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    from_state=previous_state.value,
                    to_state=result.memory.state.value,
                    active_signal_id=result.memory.active_signal_id,
                )
            )
        if result.exit_reason is not None:
            active_signal_id = result.memory.active_signal_id
            if active_signal_id is None:
                raise RuntimeError("exit intent has no active signal id")
            events.append(
                _event_record(
                    event_type="EXIT_INTENT",
                    observation=observation,
                    parameter_id=selected.parameter_id,
                    panel_snapshot_id=panel_snapshot_id,
                    is_evaluation=is_evaluation,
                    from_state=previous_state.value,
                    to_state=result.memory.state.value,
                    active_signal_id=active_signal_id,
                    reason=result.exit_reason.value,
                )
            )
        memory = result.memory
        if observation.tradable:
            trading_index += 1

    if symbol is not None and isinstance(
        anchor_retention_resolver, StreamingLineageSession
    ):
        anchor_retention_resolver.release_symbol(symbol)

    return GeneratedSignalEvents(
        signals=tuple(signals),
        events=tuple(events),
        input_rows=input_rows,
        evaluation_rows=evaluation_rows,
        evaluation_signal_rows=evaluation_signal_rows,
    )


def build_strategy_signals(
    config: MarkupRetestConfig,
    panel: PanelBuildResult,
    stage: StrategyStage | str,
    *,
    parameters: StrategyParameters | None = None,
    reuse: bool = True,
    threads: int | None = None,
) -> SignalBuildResult:
    """Stream one frozen causal panel into complete signal/event artifacts."""

    boundary = config.stage(stage)
    frozen = (
        load_passing_frozen_parameters(config)
        if boundary.name == StrategyStage.RESEALED
        else None
    )
    selected = parameters or frozen or config.parameters
    if frozen is not None and selected != frozen:
        raise ValueError("resealed signals require exactly the frozen economic parameters")
    source_input_inventory = []
    if config.assets.chip_lineage_asset_id is not None:
        source_input_inventory.append(
            verify_registered_asset_inventory(
                config, config.assets.chip_lineage_asset_id
            )
        )
    if panel.stage != boundary.name.value:
        raise ValueError(f"panel stage mismatch: {panel.stage} != {boundary.name.value}")
    if panel.config_sha256 != config.sha256:
        raise ValueError("panel and strategy config hashes differ")
    if not panel.path.is_dir():
        raise FileNotFoundError(f"causal panel directory is missing: {panel.path}")

    target = signal_path(config, boundary.name, selected)
    manifest_path = target / "manifest.json"
    builder_sha256 = _sha256(Path(__file__))
    strategy_sha256 = _sha256(Path(__file__).with_name("markup_retest.py"))
    if reuse and manifest_path.is_file():
        return _load_manifest(
            manifest_path,
            config_sha256=config.sha256,
            panel_snapshot_id=panel.panel_snapshot_id,
            parameter_id=selected.parameter_id,
            builder_sha256=builder_sha256,
            strategy_sha256=strategy_sha256,
            expected_source_inventory=source_input_inventory,
        )
    if target.exists():
        raise FileExistsError(
            f"signal target exists without a reusable matching manifest: {target}"
        )

    signal_scan_root = panel.path.parent / "panel_signal_scan"
    panel_files = tuple(
        sorted(
            (signal_scan_root if signal_scan_root.is_dir() else panel.path).rglob(
                "*.parquet"
            )
        )
    )
    if not panel_files:
        raise FileNotFoundError(f"causal panel has no parquet files: {panel.path}")
    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)

    try:
        shard_metrics = _generate_panel_event_shards(
            panel_files,
            config,
            parameters=selected,
            panel_snapshot_id=panel.panel_snapshot_id,
            panel_rows=panel.rows,
            threads=threads,
            output_root=temp,
        )
        artifact_files = tuple(temp / path for path in shard_metrics.files)
        signal_symbols = len(shard_metrics.signal_symbols)
        inventory = _inventory(temp, artifact_files)
        snapshot_payload = {
            **semantic_fingerprint_fields(),
            "schema_version": SIGNAL_SCHEMA_VERSION,
            "strategy_version": config.strategy_version,
            "stage": boundary.name.value,
            "config_sha256": config.sha256,
            "panel_snapshot_id": panel.panel_snapshot_id,
            "parameter_id": selected.parameter_id,
            "parameters": selected.canonical(),
            "builder_sha256": builder_sha256,
            "strategy_sha256": strategy_sha256,
            "selection_policy": "ALL_THRESHOLD_QUALIFIED_NO_TOP_N",
            "source_input_inventory": source_input_inventory,
            "inventory": inventory,
            "metrics": {
                "rows": shard_metrics.input_rows,
                "evaluation_rows": shard_metrics.evaluation_rows,
                "signal_rows": shard_metrics.signal_rows,
                "evaluation_signal_rows": shard_metrics.evaluation_signal_rows,
                "event_rows": shard_metrics.event_rows,
                "symbols": signal_symbols,
            },
        }
        signal_snapshot_id = (
            "signals-" + hashlib.sha256(_canonical(snapshot_payload).encode()).hexdigest()
        )
        payload = {
            **snapshot_payload,
            "status": "COMPLETE",
            "created_at": datetime.now(UTC).isoformat(),
            "signal_snapshot_id": signal_snapshot_id,
            "predictor_only_input": True,
            "label_access": "FORBIDDEN",
            "portfolio_capacity_filter": "NONE",
            "warmup_policy": "PROCESS_HISTORY_EMIT_EVALUATION_MARKER",
        }
        (temp / "manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.rename(target)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    return _load_manifest(
        target / "manifest.json",
        config_sha256=config.sha256,
        panel_snapshot_id=panel.panel_snapshot_id,
        parameter_id=selected.parameter_id,
        builder_sha256=builder_sha256,
        strategy_sha256=strategy_sha256,
        expected_source_inventory=source_input_inventory,
    )


def _generate_panel_event_shards(
    files: Sequence[Path],
    config: MarkupRetestConfig,
    *,
    parameters: StrategyParameters,
    panel_snapshot_id: str,
    panel_rows: int,
    threads: int | None,
    output_root: Path,
) -> SignalShardMetrics:
    groups = _group_panel_files(files)
    lineage_root = config.assets.chip_lineage_root
    requested_workers = threads if threads is not None else (os.cpu_count() or 1)
    worker_count = min(max(requested_workers, 1), 10, len(groups))
    arguments = tuple(
        (
            index, group, config, parameters, panel_snapshot_id, lineage_root,
            output_root,
        )
        for index, group in enumerate(groups)
    )
    if worker_count == 1 or (panel_rows < 100_000 and lineage_root is None):
        metrics = tuple(_write_panel_group_shards(argument) for argument in arguments)
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            metrics = tuple(executor.map(_write_panel_group_shards, arguments))
    return SignalShardMetrics(
        input_rows=sum(item.input_rows for item in metrics),
        evaluation_rows=sum(item.evaluation_rows for item in metrics),
        signal_rows=sum(item.signal_rows for item in metrics),
        evaluation_signal_rows=sum(item.evaluation_signal_rows for item in metrics),
        event_rows=sum(item.event_rows for item in metrics),
        signal_symbols=tuple(sorted({s for item in metrics for s in item.signal_symbols})),
        files=tuple(path for item in metrics for path in item.files),
    )


def _write_panel_group_shards(
    arguments: tuple[
        int, tuple[Path, ...], MarkupRetestConfig, StrategyParameters, str,
        Path | None, Path,
    ],
) -> SignalShardMetrics:
    index, files, config, parameters, panel_snapshot_id, lineage_root, output_root = arguments
    generated = generate_signal_events(
        stream_panel(files, strict_schema=True), config, parameters=parameters,
        panel_snapshot_id=panel_snapshot_id,
        anchor_retention_resolver=(
            StreamingLineageSession(lineage_root) if lineage_root is not None else None
        ),
    )
    signal_relative = f"signals/part-{index:03d}.parquet"
    event_relative = f"events/part-{index:03d}.parquet"
    _write_records(output_root / signal_relative, generated.signals, _signal_schema())
    _write_records(output_root / event_relative, generated.events, _event_schema())
    return SignalShardMetrics(
        input_rows=generated.input_rows,
        evaluation_rows=generated.evaluation_rows,
        signal_rows=len(generated.signals),
        evaluation_signal_rows=generated.evaluation_signal_rows,
        event_rows=len(generated.events),
        signal_symbols=tuple(sorted({str(row["symbol"]) for row in generated.signals})),
        files=(signal_relative, event_relative),
    )


def _generate_panel_events(
    files: Sequence[Path],
    config: MarkupRetestConfig,
    *,
    parameters: StrategyParameters,
    panel_snapshot_id: str,
    panel_rows: int,
    threads: int | None,
) -> GeneratedSignalEvents:
    groups = _group_panel_files(files)
    lineage_root = config.assets.chip_lineage_root
    requested_workers = threads if threads is not None else (os.cpu_count() or 1)
    worker_count = min(max(requested_workers, 1), 10, len(groups))
    # Exact lineage replay is CPU-heavy even for a small row count.  Keep the
    # old serial shortcut only for scalar/precomputed feature runs.
    if (panel_rows < 100_000 and lineage_root is None) or worker_count == 1:
        return generate_signal_events(
            stream_panel(files),
            config,
            parameters=parameters,
            panel_snapshot_id=panel_snapshot_id,
            anchor_retention_resolver=(
                StreamingLineageSession(lineage_root)
                if lineage_root is not None
                else None
            ),
        )

    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        generated_groups = tuple(
            executor.map(
                _generate_panel_group,
                (
                    (group, config, parameters, panel_snapshot_id, lineage_root)
                    for group in groups
                ),
            )
        )
    signals = tuple(
        sorted(
            (row for generated in generated_groups for row in generated.signals),
            key=lambda row: (str(row["symbol"]), str(row["decision_at"])),
        )
    )
    events = tuple(
        sorted(
            (row for generated in generated_groups for row in generated.events),
            key=lambda row: (
                str(row["symbol"]),
                str(row["decision_at"]),
                str(row["event_id"]),
            ),
        )
    )
    return GeneratedSignalEvents(
        signals=signals,
        events=events,
        input_rows=sum(item.input_rows for item in generated_groups),
        evaluation_rows=sum(item.evaluation_rows for item in generated_groups),
        evaluation_signal_rows=sum(item.evaluation_signal_rows for item in generated_groups),
    )


def _generate_panel_group(
    arguments: tuple[
        tuple[Path, ...],
        MarkupRetestConfig,
        StrategyParameters,
        str,
        Path | None,
    ],
) -> GeneratedSignalEvents:
    files, config, parameters, panel_snapshot_id, lineage_root = arguments
    return generate_signal_events(
        stream_panel(files),
        config,
        parameters=parameters,
        panel_snapshot_id=panel_snapshot_id,
        anchor_retention_resolver=(
            StreamingLineageSession(lineage_root)
            if lineage_root is not None
            else None
        ),
    )


def _group_panel_files(files: Sequence[Path]) -> tuple[tuple[Path, ...], ...]:
    grouped: dict[str, list[Path]] = {}
    for path in files:
        bucket = next(
            (part.partition("=")[2] for part in path.parts if part.startswith("symbol_bucket=")),
            "unpartitioned",
        )
        grouped.setdefault(bucket, []).append(path)
    return tuple(tuple(sorted(grouped[bucket])) for bucket in sorted(grouped))


def stream_panel(
    files: Sequence[Path],
    *,
    symbols: Sequence[str] | None = None,
    strict_schema: bool = False,
) -> Iterator[Mapping[str, object]]:
    """Yield one frozen panel scan in canonical symbol/date order."""
    sql_files = "[" + ",".join(_sql_text(str(path)) for path in files) + "]"
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        described = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({sql_files})"
        ).fetchall()
        available = {str(row[0]) for row in described}
        missing = set(_SIGNAL_INPUT_COLUMNS) - available
        if strict_schema and missing:
            raise ValueError(f"panel_signal_scan schema drift: {sorted(missing)}")
        projected_columns = ", ".join(
            f'"{column}"'
            if column in available
            else f'NULL AS "{column}"'
            for column in _SIGNAL_INPUT_COLUMNS
        )
        symbol_filter = ""
        if symbols is not None:
            if not symbols:
                return
            symbol_sql = ",".join(_sql_text(symbol) for symbol in symbols)
            symbol_filter = f"WHERE symbol IN ({symbol_sql})"
        order_clause = "" if strict_schema else "ORDER BY symbol, trade_date"
        query = con.execute(
            f"""
            SELECT {projected_columns}
            FROM read_parquet({sql_files})
            {symbol_filter}
            {order_clause}
            """
        )
        reader = query.fetch_record_batch(65_536)
        for batch in reader:
            names = batch.schema.names
            columns = [batch.column(index) for index in range(len(names))]
            for row_index in range(batch.num_rows):
                yield {
                    name: column[row_index].as_py()
                    for name, column in zip(names, columns, strict=True)
                }
    finally:
        con.close()


def observation_from_record(
    record: Mapping[str, object],
    config: MarkupRetestConfig,
    panel_snapshot_id: str,
) -> LifecycleObservation:
    """Build the sole label-blind lifecycle observation representation."""
    decision_at = _as_datetime(record.get("decision_at"), field="decision_at")
    available_at = _as_datetime(record.get("available_at"), field="available_at")
    daily_snapshot = _required_text(record, "daily_snapshot_id")
    feature_snapshot = _required_text(record, "feature_daily_snapshot_id")
    snapshot_ids = [daily_snapshot, feature_snapshot]
    minute_snapshot = _optional_text(record.get("feature_minute_snapshot_id"))
    if minute_snapshot:
        snapshot_ids.append(minute_snapshot)
    snapshot_ids.append(panel_snapshot_id)

    chip_profile, profile_valid = _chip_profile_from_record(record, config)
    peak_track_id = _optional_text(record.get("peak_track_id"))
    peak_band_lower = _optional_finite_number(record.get("peak_track_band_lower"))
    peak_band_upper = _optional_finite_number(record.get("peak_track_band_upper"))
    peak_definition_version = _optional_text(record.get("peak_definition_version"))
    peak_ambiguous = _as_bool(record.get("peak_track_ambiguous"))
    peak_valid = bool(
        peak_track_id
        and not peak_ambiguous
        and peak_definition_version == PEAK_DEFINITION_VERSION
        and peak_band_lower is not None
        and peak_band_lower > 0.0
        and peak_band_upper is not None
        and peak_band_upper >= peak_band_lower
    )
    hard_valid = (
        _as_bool(record.get("research_hard_valid"))
        and profile_valid
        and peak_valid
    )
    history_count = _finite_number(record.get("history_count"), fallback=0.0)
    setup_score = _finite_number(record.get("setup_score"), fallback=0.0)
    if history_count < config.windows.accumulation:
        setup_score = 0.0
    strict = _as_bool(record.get("strict_hard_valid"))
    industry_grade = _optional_text(record.get("effective_industry_pit_grade")) or (
        _optional_text(record.get("industry_pit_grade")) or "UNKNOWN"
    )
    pit_grade = "A" if strict else "B_RESEARCH_ONLY"
    evidence_for = tuple(label for field, label in _SETUP_EVIDENCE if _as_bool(record.get(field)))
    distribution_flags = tuple(
        _as_bool(record.get(field)) for field, _ in _DISTRIBUTION_EVIDENCE
    )
    evidence_against = tuple(
        label
        for (field, label), active in zip(
            _DISTRIBUTION_EVIDENCE, distribution_flags, strict=True
        )
        if active
    )
    atr = _positive_number(record.get("atr"), fallback=1e-12)
    current_close = _finite_number(record.get("close"), fallback=0.0)
    current_p90 = _positive_number(
        record.get("cost_p90"), fallback=chip_profile.prices[-1]
    )
    alternatives: list[str] = []
    sector_fallback = _optional_text(record.get("sector_fallback"))
    if sector_fallback and sector_fallback != "INDUSTRY_LOO":
        alternatives.append(f"sector_fallback={sector_fallback}")
    if industry_grade != "A":
        alternatives.append(f"industry_pit_grade={industry_grade}")
    reason_codes = _optional_text(record.get("reason_codes"))
    if reason_codes:
        alternatives.extend(f"data_reason={item}" for item in reason_codes.split("|") if item)
    if _as_bool(record.get("corporate_action_blocking")):
        alternatives.append("corporate_action_pending_or_unresolved")
    if not profile_valid:
        alternatives.append("chip_profile_missing_or_invalid")
    if not peak_valid:
        alternatives.append("tracked_base_peak_missing_or_ambiguous")
    lineage_state = _optional_text(record.get("exact_lineage_state")) or "UNKNOWN"
    if lineage_state == "UNKNOWN":
        alternatives.append("exact_descendant_lineage=UNKNOWN")

    # Seller source is latent.  Preserve disagreement as auditable evidence;
    # the lifecycle applies the configured observability gate before entry.
    # Residual global-p90 overhang remains explanatory rather than a hard gate.
    # A missing interval is unknown, never zero disagreement.  Keep a finite
    # sentinel because the immutable observation contract rejects NaN/inf.
    model_spread_atr = 1.0e12
    if record.get("known_cost_fraction_min") is not None:
        known_cost_fraction = min(
            1.0,
            max(
                0.0,
                _finite_number(
                    record.get("known_cost_fraction_min"), fallback=0.0
                ),
            ),
        )
        spread_fields = (
            "model_spread_cost_p50",
            "model_spread_cost_p90",
            "model_spread_dominant_peak_today",
        )
        spread_values = tuple(
            _optional_finite_number(record.get(field)) for field in spread_fields
        )
        known_spreads = tuple(value for value in spread_values if value is not None)
        if len(known_spreads) == len(spread_fields):
            model_spread_atr = max(
                0.0,
                *(value / atr for value in known_spreads),
            )
        else:
            alternatives.append("chip_model_disagreement=UNKNOWN")
        observability = known_cost_fraction / (1.0 + model_spread_atr)
        alternatives.extend(
            (
                f"known_cost_fraction={known_cost_fraction:.6f}",
                f"chip_model_disagreement_atr={model_spread_atr:.6f}",
                f"chip_observability_score={observability:.6f}",
            )
        )
    else:
        hard_valid = False
        alternatives.append("known_cost_fraction=UNKNOWN")
    if current_p90 > current_close:
        alternatives.append(
            f"global_p90_overhang_atr={(current_p90 - current_close) / atr:.6f}"
        )

    distribution_score = sum(distribution_flags) / config.fixed.distribution_component_count
    return LifecycleObservation(
        symbol=_required_text(record, "symbol"),
        decision_at=decision_at,
        available_at=available_at,
        snapshot_ids=tuple(snapshot_ids),
        hard_valid=hard_valid,
        tradable=_as_bool(record.get("tradable_state")),
        pit_grade=pit_grade,
        setup_score=setup_score,
        breakout_excess_atr=_finite_number(record.get("breakout_excess_atr"), fallback=-1e12),
        support_regained=_as_bool(record.get("support_regained")),
        downside_absorption=_as_bool(record.get("ev_downside_absorption")),
        chip_profile=chip_profile,
        cost_p10=_positive_number(record.get("cost_p10"), fallback=chip_profile.prices[0]),
        cost_p90=current_p90,
        peak_count=max(1, int(_finite_number(record.get("peak_count"), fallback=1.0))),
        recent_band_overlap=_finite_number(
            record.get("recent_band_overlap"), fallback=0.0
        ),
        distribution_score=distribution_score,
        structure_support=_finite_number(record.get("structure_support"), fallback=0.0),
        close=current_close,
        close_vs_vwap=_finite_number(
            record.get("close_vs_vwap"),
            fallback=0.0 if _as_bool(record.get("support_regained")) else -1e12,
        ),
        low=_finite_number(record.get("low"), fallback=0.0),
        volume=_finite_number(record.get("volume"), fallback=0.0),
        turnover=_finite_number(record.get("turnover_fraction"), fallback=0.0),
        average_cost=_finite_number(record.get("average_cost"), fallback=0.0),
        cost_p50=_finite_number(record.get("cost_p50"), fallback=0.0),
        prior_average_cost=_finite_number(record.get("prior_average_cost"), fallback=0.0),
        prior_cost_p50=_finite_number(record.get("prior_cost_p50"), fallback=0.0),
        atr=atr,
        chip_model_disagreement_atr=model_spread_atr,
        share_multiplier=_positive_number(
            record.get("share_multiplier"), fallback=1.0
        ),
        cash_per_share=max(
            0.0, _finite_number(record.get("cash_per_share"), fallback=0.0)
        ),
        structure_broken=_as_bool(record.get("structure_broken")),
        corporate_action_blocking=_as_bool(record.get("corporate_action_blocking")),
        corporate_action_ids=parse_action_ids(record.get("corporate_action_ids")),
        market_state=_optional_text(record.get("market_state")) or "UNKNOWN",
        sector_state=_optional_text(record.get("sector_state")) or "UNKNOWN",
        industry_pit_grade=industry_grade,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        alternative_explanations=tuple(dict.fromkeys(alternatives)),
        anchor_retention_estimates=_anchor_retention_estimates_from_record(record),
        peak_track_id=peak_track_id,
        peak_track_band_lower=peak_band_lower,
        peak_track_band_upper=peak_band_upper,
        peak_track_ambiguous=peak_ambiguous,
        peak_definition_version=peak_definition_version,
    )


def serialize_signal(
    signal: StrategySignal,
    *,
    panel_snapshot_id: str,
    is_evaluation: bool,
) -> dict[str, Any]:
    """Serialize a canonical strategy signal for materialized artifacts."""
    return {
        "signal_id": signal.signal_id,
        "symbol": signal.symbol,
        "decision_at": signal.decision_at.isoformat(),
        "strategy_version": signal.strategy_version,
        "strategy_family": signal.strategy_family.value,
        "lifecycle_state": signal.lifecycle_state.value,
        "accumulation_started_at": signal.accumulation_started_at.isoformat(),
        "breakout_at": signal.breakout_at.isoformat(),
        "retest_confirmed_at": signal.retest_confirmed_at.isoformat(),
        "anchor_created_at": signal.anchor_created_at.isoformat(),
        "anchor_lower": signal.anchor_lower,
        "anchor_upper": signal.anchor_upper,
        "anchor_reference_mass": signal.anchor_reference_mass,
        "anchor_retention": signal.anchor_retention,
        "anchor_mass_method": signal.anchor_mass_method.value,
        "root_anchor_id": signal.root_anchor_id,
        "working_anchor_id": signal.working_anchor_id,
        "anchor_chain_ids": list(signal.anchor_chain_ids),
        "anchor_retention_lower": signal.anchor_retention_lower,
        "anchor_retention_upper": signal.anchor_retention_upper,
        "anchor_retention_confidence": signal.anchor_retention_confidence,
        "anchor_model_retentions": [
            {"model": model, "retention": retention}
            for model, retention in signal.anchor_model_retentions
        ],
        "evidence_for": list(signal.evidence_for),
        "evidence_against": list(signal.evidence_against),
        "market_state": signal.market_state,
        "sector_state": signal.sector_state,
        "alternative_explanations": list(signal.alternative_explanations),
        "available_at": signal.available_at.isoformat(),
        "snapshot_ids": list(signal.snapshot_ids),
        "panel_snapshot_id": panel_snapshot_id,
        "hard_valid": signal.hard_valid,
        "pit_grade": signal.pit_grade,
        "industry_pit_grade": signal.industry_pit_grade,
        "parameter_id": signal.parameter_id,
        "edge_card": None,
        "execution_status": signal.execution_status,
        "unfilled_reason": signal.unfilled_reason,
        "is_evaluation_row": is_evaluation,
    }


def _event_record(
    *,
    event_type: str,
    observation: LifecycleObservation,
    parameter_id: str,
    panel_snapshot_id: str,
    is_evaluation: bool,
    from_state: str,
    to_state: str,
    active_signal_id: str | None,
    reason: str | None = None,
) -> dict[str, Any]:
    identity = "|".join(
        (
            event_type,
            observation.symbol,
            observation.decision_at.isoformat(),
            parameter_id,
            active_signal_id or "",
            reason or "",
        )
    )
    return {
        "event_id": hashlib.sha256(identity.encode()).hexdigest(),
        "event_type": event_type,
        "symbol": observation.symbol,
        "decision_at": observation.decision_at.isoformat(),
        "available_at": observation.available_at.isoformat(),
        "from_state": from_state,
        "to_state": to_state,
        "active_signal_id": active_signal_id,
        "reason": reason,
        "parameter_id": parameter_id,
        "panel_snapshot_id": panel_snapshot_id,
        "snapshot_ids": list(observation.snapshot_ids),
        "hard_valid": observation.hard_valid,
        "pit_grade": observation.pit_grade,
        "is_evaluation_row": is_evaluation,
    }


def _signal_schema() -> pa.Schema:
    return pa.schema(
        [
            ("signal_id", pa.string()),
            ("symbol", pa.string()),
            ("decision_at", pa.string()),
            ("strategy_version", pa.string()),
            ("strategy_family", pa.string()),
            ("lifecycle_state", pa.string()),
            ("accumulation_started_at", pa.string()),
            ("breakout_at", pa.string()),
            ("retest_confirmed_at", pa.string()),
            ("anchor_created_at", pa.string()),
            ("anchor_lower", pa.float64()),
            ("anchor_upper", pa.float64()),
            ("anchor_reference_mass", pa.float64()),
            ("anchor_retention", pa.float64()),
            ("anchor_mass_method", pa.string()),
            ("root_anchor_id", pa.string()),
            ("working_anchor_id", pa.string()),
            ("anchor_chain_ids", pa.list_(pa.string())),
            ("anchor_retention_lower", pa.float64()),
            ("anchor_retention_upper", pa.float64()),
            ("anchor_retention_confidence", pa.float64()),
            (
                "anchor_model_retentions",
                pa.list_(
                    pa.struct(
                        [("model", pa.string()), ("retention", pa.float64())]
                    )
                ),
            ),
            ("evidence_for", pa.list_(pa.string())),
            ("evidence_against", pa.list_(pa.string())),
            ("market_state", pa.string()),
            ("sector_state", pa.string()),
            ("alternative_explanations", pa.list_(pa.string())),
            ("available_at", pa.string()),
            ("snapshot_ids", pa.list_(pa.string())),
            ("panel_snapshot_id", pa.string()),
            ("hard_valid", pa.bool_()),
            ("pit_grade", pa.string()),
            ("industry_pit_grade", pa.string()),
            ("parameter_id", pa.string()),
            ("edge_card", pa.string()),
            ("execution_status", pa.string()),
            ("unfilled_reason", pa.string()),
            ("is_evaluation_row", pa.bool_()),
        ]
    )


def _event_schema() -> pa.Schema:
    return pa.schema(
        [
            ("event_id", pa.string()),
            ("event_type", pa.string()),
            ("symbol", pa.string()),
            ("decision_at", pa.string()),
            ("available_at", pa.string()),
            ("from_state", pa.string()),
            ("to_state", pa.string()),
            ("active_signal_id", pa.string()),
            ("reason", pa.string()),
            ("parameter_id", pa.string()),
            ("panel_snapshot_id", pa.string()),
            ("snapshot_ids", pa.list_(pa.string())),
            ("hard_valid", pa.bool_()),
            ("pit_grade", pa.string()),
            ("is_evaluation_row", pa.bool_()),
        ]
    )


def _write_records(path: Path, records: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    arrays = [
        pa.array([record.get(field.name) for record in records], type=field.type)
        for field in schema
    ]
    table = pa.Table.from_arrays(arrays, schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def _inventory(root: Path, paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _load_manifest(
    path: Path,
    *,
    config_sha256: str,
    panel_snapshot_id: str,
    parameter_id: str,
    builder_sha256: str,
    strategy_sha256: str,
    expected_source_inventory: list[dict[str, Any]],
) -> SignalBuildResult:
    payload = json.loads(path.read_text())
    require_active_semantic_epoch(payload, artifact_name="signals")
    expected = {
        "status": "COMPLETE",
        "schema_version": SIGNAL_SCHEMA_VERSION,
        "config_sha256": config_sha256,
        "panel_snapshot_id": panel_snapshot_id,
        "parameter_id": parameter_id,
        "builder_sha256": builder_sha256,
        "strategy_sha256": strategy_sha256,
        "selection_policy": "ALL_THRESHOLD_QUALIFIED_NO_TOP_N",
        "label_access": "FORBIDDEN",
        "portfolio_capacity_filter": "NONE",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"signal manifest {key} mismatch: {path}")
    if payload.get("source_input_inventory") != expected_source_inventory:
        raise ValueError(f"signal manifest source input inventory mismatch: {path}")
    _verify_inventory(path.parent, payload)
    snapshot_payload = semantic_fingerprint_fields()
    snapshot_payload.update(
        {
            key: payload[key]
            for key in (
            "schema_version",
            "strategy_version",
            "stage",
            "config_sha256",
            "panel_snapshot_id",
            "parameter_id",
            "parameters",
            "builder_sha256",
            "strategy_sha256",
            "selection_policy",
            "source_input_inventory",
            "inventory",
            "metrics",
        )
        }
    )
    expected_snapshot = (
        "signals-" + hashlib.sha256(_canonical(snapshot_payload).encode()).hexdigest()
    )
    if payload.get("signal_snapshot_id") != expected_snapshot:
        raise ValueError(f"signal snapshot hash mismatch: {path}")
    metrics = payload["metrics"]
    return SignalBuildResult(
        stage=str(payload["stage"]),
        status=str(payload["status"]),
        path=path.parent,
        manifest_path=path,
        rows=int(metrics["rows"]),
        evaluation_rows=int(metrics["evaluation_rows"]),
        signal_rows=int(metrics["signal_rows"]),
        evaluation_signal_rows=int(metrics["evaluation_signal_rows"]),
        event_rows=int(metrics["event_rows"]),
        symbols=int(metrics["symbols"]),
        config_sha256=str(payload["config_sha256"]),
        panel_snapshot_id=str(payload["panel_snapshot_id"]),
        signal_snapshot_id=str(payload["signal_snapshot_id"]),
        parameter_id=str(payload["parameter_id"]),
    )


def _verify_inventory(root: Path, payload: Mapping[str, Any]) -> None:
    inventory = payload.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError(f"signal artifact inventory is missing: {root}")
    for raw in inventory:
        if not isinstance(raw, dict):
            raise ValueError(f"invalid signal inventory entry: {root}")
        relative = Path(str(raw.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe signal inventory path: {relative}")
        artifact = root / relative
        if not artifact.is_file():
            raise ValueError(f"signal inventory path is missing: {artifact}")
        if artifact.stat().st_size != raw.get("size"):
            raise ValueError(f"signal inventory size mismatch: {artifact}")
        if _sha256(artifact) != raw.get("sha256"):
            raise ValueError(f"signal inventory hash mismatch: {artifact}")


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = _optional_text(record.get(field))
    if not value:
        raise ValueError(f"signal input requires {field}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() not in {"nan", "none", "null"} else None


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value) if math.isfinite(float(value)) else False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _finite_number(value: object, *, fallback: float) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _optional_finite_number(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_number(value: object, *, fallback: float) -> float:
    number = _finite_number(value, fallback=fallback)
    return number if number > 0 else fallback


def _as_date(value: object, *, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value!r}") from error


def _as_datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time(15, 30))
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"invalid {field}: {value!r}") from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=CN_TZ)
    return parsed.astimezone(CN_TZ)


def _decoded(value: object) -> object:
    if value is None:
        return None
    as_py = getattr(value, "as_py", None)
    if callable(as_py):
        value = as_py()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped[0] in "[{":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return None
    return value


def _number_sequence(value: object) -> tuple[float, ...] | None:
    decoded = _decoded(value)
    if decoded is None or isinstance(decoded, (str, bytes, Mapping)):
        return None
    if not isinstance(decoded, Iterable):
        return None
    try:
        values = tuple(float(item) for item in decoded)
    except (TypeError, ValueError):
        return None
    if not values or any(not math.isfinite(item) for item in values):
        return None
    return values


def _chip_profile_from_record(
    record: Mapping[str, object], config: MarkupRetestConfig
) -> tuple[ChipMassProfile, bool]:
    direct = _decoded(record.get("chip_profile"))
    if isinstance(direct, ChipMassProfile):
        return direct, True
    if isinstance(direct, Mapping):
        prices = _number_sequence(direct.get("prices"))
        masses = _number_sequence(direct.get("masses"))
        if prices is not None and masses is not None:
            try:
                return (
                    ChipMassProfile.from_histogram(
                        prices=prices,
                        masses=masses,
                        mass_tolerance=config.quality.mass_tolerance,
                    ),
                    True,
                )
            except ValueError:
                pass

    for price_field, mass_field in (
        ("chip_histogram_prices", "chip_histogram_masses"),
        ("chip_prices", "chip_masses"),
    ):
        prices = _number_sequence(record.get(price_field))
        masses = _number_sequence(record.get(mass_field))
        if prices is None or masses is None:
            continue
        try:
            return (
                ChipMassProfile.from_histogram(
                    prices=prices,
                    masses=masses,
                    mass_tolerance=config.quality.mass_tolerance,
                ),
                True,
            )
        except ValueError:
            continue

    p10 = _finite_number(record.get("cost_p10"), fallback=math.nan)
    p50 = _finite_number(record.get("cost_p50"), fallback=math.nan)
    p90 = _finite_number(record.get("cost_p90"), fallback=math.nan)
    p01 = _finite_number(record.get("cost_p01"), fallback=p10)
    p99 = _finite_number(record.get("cost_p99"), fallback=p90)
    return (
        ChipMassProfile.from_quantiles(
            p01=p01,
            p10=p10,
            p50=p50,
            p90=p90,
            p99=p99,
        ),
        True,
    )


def _anchor_retention_estimates_from_record(
    record: Mapping[str, object],
) -> tuple[AnchorRetentionEstimate, ...]:
    raw = _decoded(record.get("anchor_retention_estimates"))
    if raw is None:
        raw = _decoded(record.get("anchor_lineage_estimates"))
    if raw is None:
        scalar_models = {
            SellerModel.UNIFORM: record.get("anchor_uniform_retention"),
            SellerModel.DISPOSITION: record.get("anchor_disposition_retention"),
            SellerModel.ACTIVE_STICKY: record.get("anchor_active_sticky_retention"),
        }
        if all(value is not None for value in scalar_models.values()):
            raw = [
                {
                    "anchor_id": record.get("anchor_id"),
                    "symbol": record.get("symbol"),
                    "anchor_date": record.get("anchor_date"),
                    "current_date": record.get("trade_date"),
                    "model_retentions": scalar_models,
                    "ensemble_version": record.get("anchor_ensemble_version")
                    or "chip-lineage-v2",
                }
            ]
    if raw is None:
        return ()
    if isinstance(raw, AnchorRetentionEstimate):
        return (raw,)
    if isinstance(raw, Mapping):
        if "anchor_id" in raw:
            items: Sequence[object] = (raw,)
        else:
            items = tuple(raw.values())
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        items = raw
    else:
        return ()

    estimates: list[AnchorRetentionEstimate] = []
    for item in items:
        decoded = _decoded(item)
        if isinstance(decoded, AnchorRetentionEstimate):
            estimates.append(decoded)
            continue
        if not isinstance(decoded, Mapping):
            continue
        model_values = _decoded(decoded.get("model_retentions"))
        if isinstance(model_values, Sequence) and not isinstance(model_values, (str, bytes)):
            model_values = {
                str(entry.get("model")): entry.get("retention")
                for entry in model_values
                if isinstance(entry, Mapping)
            }
        if not isinstance(model_values, Mapping):
            continue
        try:
            estimates.append(
                AnchorRetentionEstimate.from_model_retentions(
                    anchor_id=str(decoded["anchor_id"]),
                    symbol=str(decoded["symbol"]),
                    anchor_date=_as_date(decoded.get("anchor_date"), field="anchor_date"),
                    current_date=_as_date(
                        decoded.get("current_date"), field="anchor_current_date"
                    ),
                    model_retentions={
                        str(key): float(value) for key, value in model_values.items()
                    },
                    ensemble_version=str(
                        decoded.get("ensemble_version") or "chip-lineage-v2"
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(
        sorted(
            estimates,
            key=lambda item: (
                item.symbol,
                item.anchor_date,
                item.anchor_id,
                item.current_date,
            ),
        )
    )


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


_SETUP_EVIDENCE = (
    ("ev_turnover_absorption", "high_turnover_low_price_impact"),
    ("ev_near_price_chip_growth", "asr_and_near_price_chip_growth"),
    ("ev_concentration_improves", "cost_band_narrows_and_concentration_improves"),
    ("ev_sticky_base", "sticky_base_and_stable_main_peak"),
    ("ev_downside_absorption", "downside_absorption_and_intraday_support"),
)

_DISTRIBUTION_EVIDENCE = (
    ("dist_cost_band_expands", "high_cost_chips_or_cost_band_expands"),
    ("dist_peak_splits", "concentration_deteriorates_or_peak_splits"),
    ("dist_high_turnover_weak_impact", "high_turnover_with_weak_upside_impact"),
    ("dist_relative_reversal", "market_and_sector_relative_strength_reverses"),
)

_SIGNAL_INPUT_COLUMNS = (
    "symbol",
    "trade_date",
    "decision_at",
    "available_at",
    "daily_snapshot_id",
    "feature_daily_snapshot_id",
    "feature_minute_snapshot_id",
    "research_hard_valid",
    "strict_hard_valid",
    "tradable_state",
    "history_count",
    "setup_score",
    "breakout_excess_atr",
    "support_regained",
    "distribution_score",
    "cost_p01",
    "cost_p10",
    "structure_support",
    "close",
    "preclose",
    "close_vs_vwap",
    "low",
    "volume",
    "turnover_fraction",
    "average_cost",
    "cost_p50",
    "cost_p90",
    "state_quality",
    "known_cost_fraction_min",
    "model_spread_cost_p50",
    "model_spread_cost_p90",
    "model_spread_main_peak",
    "model_spread_dominant_peak_today",
    "peak_track_id",
    "peak_track_band_lower",
    "peak_track_band_upper",
    "peak_track_ambiguous",
    "peak_definition_version",
    "exact_lineage_state",
    "cost_p99",
    "peak_count",
    "recent_band_overlap",
    "chip_profile",
    "chip_histogram_prices",
    "chip_histogram_masses",
    "chip_prices",
    "chip_masses",
    "anchor_retention_estimates",
    "anchor_lineage_estimates",
    "anchor_id",
    "anchor_date",
    "anchor_ensemble_version",
    "anchor_uniform_retention",
    "anchor_disposition_retention",
    "anchor_active_sticky_retention",
    "prior_average_cost",
    "prior_cost_p50",
    "atr",
    "share_multiplier",
    "cash_per_share",
    "structure_broken",
    "corporate_action_blocking",
    "corporate_action_ids",
    "market_state",
    "sector_state",
    "effective_industry_pit_grade",
    "industry_pit_grade",
    "sector_fallback",
    "reason_codes",
    "is_evaluation_row",
    "dist_base_loss",
    *tuple(field for field, _ in _SETUP_EVIDENCE),
    *tuple(field for field, _ in _DISTRIBUTION_EVIDENCE),
)
