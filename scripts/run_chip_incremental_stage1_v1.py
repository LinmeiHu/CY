#!/usr/bin/env python3
"""Run the single preregistered 2020-2022 chip-incremental outcome experiment."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import itertools
import json
import os
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.strategy.chip_incremental_evaluation import (  # type: ignore[import-untyped]
    FORWARD_FOLDS,
    MODULES,
    apply_holm,
    fit_module_transform,
    module_evidence,
    score_evaluation_rows,
)
from cyq_game.strategy.exact_replay import (  # type: ignore[import-untyped]
    _market_trading_dates,
    _stream_execution_windows,
)
from cyq_game.strategy.execution import ExecutionWindow  # type: ignore[import-untyped]
from cyq_game.strategy.fixed_horizon import (  # type: ignore[import-untyped]
    FixedHorizonTrade,
    PanelSession,
    evaluate_fixed_horizon_trade,
)
from cyq_game.strategy.ledger import (  # type: ignore[import-untyped]
    LedgerEntry,
    TrialLedger,
)
from cyq_game.strategy.markup_retest import (  # type: ignore[import-untyped]
    MarkupRetestConfig,
)

CN_TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path("output/chip_incremental_validation_v1")
FEATURE_MANIFEST = ROOT / "features/manifest.json"
PROTOCOL = ROOT / "protocol_manifest.json"
ADDENDA = tuple(
    ROOT / f"addenda/addendum_{index:02d}_manifest.json" for index in range(1, 6)
)
LEDGER = ROOT / "trials/events.jsonl"
STAGE_ROOT = ROOT / "stage1"
CONFIG = Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml")
REGISTRY = Path("configs/data_asset_registry.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--bootstrap-resamples", type=int, default=10_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers != 4:
        raise ValueError("stage 1 is fixed to four coalesced workers")
    if args.bootstrap_resamples != 10_000:
        raise ValueError("stage 1 requires exactly 10,000 bootstrap resamples")
    STAGE_ROOT.mkdir(parents=True, exist_ok=True)
    with (STAGE_ROOT / "run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("chip incremental stage 1 is already running") from error
        return _run(args.workers, args.bootstrap_resamples)


def _run(workers: int, bootstrap_resamples: int) -> int:
    protocol, addenda = _protocol_chain()
    feature_manifest_path = FEATURE_MANIFEST.resolve()
    feature_manifest = _object(feature_manifest_path)
    feature_path = feature_manifest_path.parent / str(feature_manifest["feature_cohort"])
    if (
        feature_manifest.get("status") != "COMPLETE_OUTCOME_BLIND"
        or feature_manifest.get("outcome_fields_used") is not False
        or feature_manifest.get("holdout_outcomes_observed") is not False
        or feature_manifest.get("feature_cohort_sha256") != _sha256(feature_path)
        or feature_manifest.get("addendum_05_event_id") != addenda[-1]["event_id"]
    ):
        raise ValueError("stage 1 feature cohort identity changed")
    config = MarkupRetestConfig.load(CONFIG)
    daily_files, daily_inventory = _daily_inputs(feature_manifest)
    execution_files, execution_inventory = _execution_inputs(config)
    run_identity = {
        "protocol_event_id": protocol["event_id"],
        "addendum_event_ids": [item["event_id"] for item in addenda],
        "feature_cohort_snapshot_id": feature_manifest["feature_cohort_snapshot_id"],
        "feature_cohort_sha256": feature_manifest["feature_cohort_sha256"],
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "evaluation_code_sha256": _sha256(
            Path("src/cyq_game/strategy/chip_incremental_evaluation.py").resolve()
        ),
        "fixed_horizon_code_sha256": _sha256(
            Path("src/cyq_game/strategy/fixed_horizon.py").resolve()
        ),
        "execution_inventory": execution_inventory,
        "daily_inventory": daily_inventory,
    }
    run_id = "chip-incremental-stage1-" + hashlib.sha256(
        _canonical(run_identity).encode()
    ).hexdigest()
    final_manifest = STAGE_ROOT / "manifest.json"
    if final_manifest.is_file():
        existing = _object(final_manifest)
        if existing.get("run_id") != run_id or existing.get("status") != "COMPLETE":
            raise FileExistsError("existing stage-1 manifest differs")
        print(json.dumps(_brief(existing), ensure_ascii=False, indent=2))
        return 0

    feature_rows = [dict(row) for row in pq.read_table(feature_path).to_pylist()]
    transforms = []
    scored: list[dict[str, Any]] = []
    for module in MODULES:
        for fold in FORWARD_FOLDS:
            transform = fit_module_transform(feature_rows, module, fold)
            transforms.append(transform)
            scored.extend(score_evaluation_rows(feature_rows, transform))
    if not scored:
        raise RuntimeError("stage 1 has no scored evaluation rows")
    transform_path = STAGE_ROOT / "frozen_transforms.json"
    scored_path = STAGE_ROOT / "scored_features.parquet"
    _write_immutable(
        transform_path,
        {
            "run_id": run_id,
            "outcomes_used": False,
            "transforms": [item.to_dict() for item in transforms],
        },
    )
    _write_parquet_immutable(scored_path, scored)

    ledger = TrialLedger(LEDGER.resolve())
    entries = ledger.read_verified()
    _assert_single_run_budget(entries, run_id)
    started_payload = {
        "event_id": _digest(f"{run_id}|STARTED"),
        "run_id": run_id,
        "protocol_event_id": protocol["event_id"],
        "feature_cohort_snapshot_id": feature_manifest["feature_cohort_snapshot_id"],
        "scored_features_sha256": _sha256(scored_path),
        "stage_1_outcome_run_number": 1,
        "maximum_physical_data_year": 2022,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
    }
    started = _append_once(ledger, "CHIP_INCREMENTAL_STAGE1_STARTED", started_payload)
    market_dates = _market_trading_dates(
        execution_files, start=date(2020, 1, 2), end=date(2022, 12, 30)
    )
    event_by_id: dict[str, dict[str, Any]] = {}
    for row in scored:
        event_by_id.setdefault(str(row["candidate_id"]), row)
    outcomes = _run_outcomes(
        run_id=run_id,
        events=tuple(event_by_id.values()),
        daily_files=daily_files,
        execution_files=execution_files,
        market_dates=market_dates,
        config=config,
        workers=workers,
    )
    outcome_by_id = {str(row["signal_id"]): row for row in outcomes}
    evaluated = [
        {
            **row,
            **{
                f"outcome_{key}": value
                for key, value in outcome_by_id[str(row["candidate_id"])].items()
                if key != "signal_id"
            },
            "return_fraction": outcome_by_id[str(row["candidate_id"])].get(
                "return_fraction"
            ),
        }
        for row in scored
    ]
    evaluated_path = STAGE_ROOT / "evaluated_events.parquet"
    _write_parquet_immutable(evaluated_path, evaluated)
    evidence = [
        module_evidence(
            evaluated,
            module,
            protocol_event_id=str(protocol["event_id"]),
            bootstrap_resamples=bootstrap_resamples,
            placebo_permutations=199,
        )
        for module in MODULES
    ]
    holm = apply_holm(evidence)
    capacity = _capacity_evidence(tuple(event_by_id.values()), outcomes)
    passing_modules: list[str] = []
    final_evidence: list[dict[str, Any]] = []
    for item in evidence:
        module = str(item["module"])
        final_pass = (
            item["status_before_holm"] == "PASS"
            and holm[module]
            and capacity["gate"] == "PASS"
        )
        final_evidence.append(
            {
                **item,
                "holm_pass": holm[module],
                "capacity_gate": capacity["gate"],
                "final_status": "PASS" if final_pass else "FAIL",
            }
        )
        if final_pass:
            passing_modules.append(module)
    if passing_modules:
        decision = "CHIP_INCREMENTAL_VALUE_PASS"
    elif capacity["gate"] != "PASS" or any(
        item["status_before_holm"] == "INSUFFICIENT_EVIDENCE"
        for item in evidence
    ):
        decision = "INSUFFICIENT_EVIDENCE"
    else:
        decision = "NO_CHIP_INCREMENTAL_VALUE"
    evidence_path = STAGE_ROOT / "module_evidence.json"
    _write_immutable(
        evidence_path,
        {
            "run_id": run_id,
            "modules": final_evidence,
            "holm_familywise_alpha": 0.05,
            "capacity": capacity,
        },
    )
    freeze: dict[str, Any] = {
        "schema_version": 1,
        "status": "FROZEN",
        "run_id": run_id,
        "decision": decision,
        "passing_modules": passing_modules,
        "stage_2_authorized": bool(passing_modules),
        "exit_tuning_authorized": False,
        "parameters_frozen": False,
        "maximum_physical_data_year": 2022,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
        "module_evidence_sha256": _sha256(evidence_path),
    }
    freeze["freeze_snapshot_id"] = "chip-incremental-freeze-" + _digest(
        _canonical(freeze)
    )
    freeze_path = STAGE_ROOT / "freeze_manifest.json"
    _write_immutable(freeze_path, freeze)
    inventory = _inventory(
        (
            transform_path,
            scored_path,
            evaluated_path,
            evidence_path,
            freeze_path,
            *(STAGE_ROOT / "outcome_parts").rglob("*.parquet"),
            *(STAGE_ROOT / "outcome_parts").rglob("manifest.json"),
        )
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "COMPLETE",
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        **run_identity,
        "started_ledger_sequence": started.sequence,
        "scored_evaluation_rows": len(scored),
        "unique_outcome_requests": len(event_by_id),
        "outcomes": len(outcomes),
        "passing_modules": passing_modules,
        "terminal_decision": decision,
        "stage_2_authorized": bool(passing_modules),
        "freeze_manifest": str(freeze_path.resolve()),
        "freeze_manifest_sha256": _sha256(freeze_path),
        "inventory": inventory,
        "maximum_physical_data_year": 2022,
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
    }
    manifest["stage1_snapshot_id"] = "chip-incremental-stage1-result-" + _digest(
        _canonical({key: value for key, value in manifest.items() if key != "created_at"})
    )
    _write_immutable(final_manifest, manifest)
    completion_payload = {
        "event_id": _digest(f"{run_id}|{manifest['stage1_snapshot_id']}|COMPLETE"),
        "run_id": run_id,
        "stage1_snapshot_id": manifest["stage1_snapshot_id"],
        "manifest_path": str(final_manifest.resolve()),
        "manifest_sha256": _sha256(final_manifest),
        "terminal_decision": decision,
        "passing_modules": passing_modules,
        "stage_1_outcome_runs_consumed": 1,
        "stage_2_authorized": bool(passing_modules),
        "holdout_accessed": False,
        "holdout_outcomes_observed": False,
    }
    completed = _append_once(
        ledger, "CHIP_INCREMENTAL_STAGE1_COMPLETE", completion_payload
    )
    print(
        json.dumps(
            {
                **_brief(manifest),
                "completion_ledger_sequence": completed.sequence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run_outcomes(
    *,
    run_id: str,
    events: tuple[dict[str, Any], ...],
    daily_files: tuple[Path, ...],
    execution_files: tuple[Path, ...],
    market_dates: tuple[date, ...],
    config: MarkupRetestConfig,
    workers: int,
) -> list[dict[str, Any]]:
    grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[int(event["symbol_bucket"])].append(event)
    assignments = [tuple(range(worker, 32, workers)) for worker in range(workers)]
    parts = STAGE_ROOT / "outcome_parts"
    parts.mkdir(exist_ok=True)
    pending = []
    for worker, buckets in enumerate(assignments):
        expected = tuple(
            event for bucket in buckets for event in grouped.get(bucket, ())
        )
        target = parts / f"worker={worker}"
        if _valid_part(target, run_id, expected):
            continue
        pending.append((worker, buckets, expected))
    if pending:
        arguments = [
            (
                worker,
                buckets,
                events_for_worker,
                daily_files,
                execution_files,
                market_dates,
                config,
            )
            for worker, buckets, events_for_worker in pending
        ]
        with ProcessPoolExecutor(
            max_workers=workers, max_tasks_per_child=1
        ) as executor:
            futures = {
                executor.submit(_outcome_worker, argument): argument[0]
                for argument in arguments
            }
            for future in as_completed(futures):
                worker = futures[future]
                outcomes, seconds = future.result()
                expected = next(item[2] for item in pending if item[0] == worker)
                _write_part(
                    parts / f"worker={worker}",
                    run_id,
                    expected,
                    outcomes,
                    seconds,
                )
                print(
                    json.dumps(
                        {
                            "outcome_worker": worker,
                            "completed_workers": sum(
                                _valid_part(
                                    parts / f"worker={index}",
                                    run_id,
                                    tuple(
                                        event
                                        for bucket in assignments[index]
                                        for event in grouped.get(bucket, ())
                                    ),
                                )
                                for index in range(workers)
                            ),
                            "total_workers": workers,
                            "outcomes": len(outcomes),
                            "wall_seconds": seconds,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    result: list[dict[str, Any]] = []
    for worker in range(workers):
        result.extend(
            dict(row)
            for row in pq.read_table(
                parts / f"worker={worker}" / "outcomes.parquet"
            ).to_pylist()
        )
    ids = {str(row["signal_id"]) for row in result}
    expected_ids = {str(row["candidate_id"]) for row in events}
    if len(result) != len(ids) or ids != expected_ids:
        raise ValueError("fixed outcomes do not exactly cover stage-1 events")
    return result


def _outcome_worker(
    args: tuple[
        int,
        tuple[int, ...],
        tuple[dict[str, Any], ...],
        tuple[Path, ...],
        tuple[Path, ...],
        tuple[date, ...],
        MarkupRetestConfig,
    ]
) -> tuple[list[dict[str, Any]], float]:
    worker, buckets, events, daily_files, execution_files, market_dates, config = args
    del worker
    started = time.perf_counter()
    symbols = tuple(sorted({str(event["symbol"]) for event in events}))
    event_groups = itertools.groupby(
        sorted(events, key=lambda row: (str(row["symbol"]), _date(row["trade_date"]))),
        key=lambda row: str(row["symbol"]),
    )
    session_groups = iter(
        itertools.groupby(
            _stream_daily_sessions(daily_files, buckets, symbols),
            key=lambda item: item.symbol,
        )
    )
    window_groups = iter(
        itertools.groupby(
            _stream_execution_windows(execution_files, buckets, symbols=symbols),
            key=lambda item: item.symbol,
        )
    )
    current_sessions = next(session_groups, None)
    current_windows = next(window_groups, None)
    outcomes: list[dict[str, Any]] = []
    for symbol, raw_events in event_groups:
        while current_sessions is not None and current_sessions[0] < symbol:
            current_sessions = next(session_groups, None)
        while current_windows is not None and current_windows[0] < symbol:
            current_windows = next(window_groups, None)
        if current_sessions is None or current_sessions[0] != symbol:
            raise ValueError(f"stage-1 outcome has no daily sessions for {symbol}")
        sessions = tuple(current_sessions[1])
        current_sessions = next(session_groups, None)
        if current_windows is not None and current_windows[0] == symbol:
            windows: tuple[ExecutionWindow, ...] = tuple(current_windows[1])
            current_windows = next(window_groups, None)
        else:
            windows = ()
        for event in raw_events:
            outcome = evaluate_fixed_horizon_trade(
                signal_id=str(event["candidate_id"]),
                symbol=symbol,
                signal_date=_date(event["trade_date"]),
                signal_decision_at=_aware(event["decision_at"]),
                signal_available_at=_aware(event["available_at"]),
                signal_snapshot_ids=tuple(
                    str(event[name])
                    for name in (
                        "daily_snapshot_id",
                        "semantic_snapshot_id",
                        "exact_daily_snapshot_id",
                        "exact_minute_snapshot_id",
                    )
                    if event.get(name)
                ),
                sessions=sessions,
                windows=windows,
                market_trading_dates=market_dates,
                settings=config.execution,
                strategy_version="CHIP_INCREMENTAL_VALIDATION_V1",
                parameter_id="FIXED_STAGE1_NO_TUNING",
                horizon_sessions=20,
            )
            outcomes.append(_outcome_row(outcome))
    return outcomes, time.perf_counter() - started


def _stream_daily_sessions(
    files: Sequence[Path], buckets: Sequence[int], symbols: Sequence[str]
) -> Iterable[PanelSession]:
    if not symbols:
        return
    symbol_sql = ",".join(_sql_text(symbol) for symbol in symbols)
    bucket_sql = ",".join(str(bucket) for bucket in buckets)
    con = duckdb.connect()
    try:
        con.execute("SET threads=1")
        reader = con.execute(
            f"""
            SELECT symbol, trade_date, decision_at, available_at, close,
                   share_multiplier, cash_per_share, daily_snapshot_id,
                   corporate_action_snapshot_id
            FROM read_parquet({_sql_list(files)}, union_by_name=true)
            WHERE abs(hash(symbol) % 32) IN ({bucket_sql})
              AND symbol IN ({symbol_sql})
              AND trade_date BETWEEN DATE '2020-01-02' AND DATE '2022-12-30'
            ORDER BY symbol, trade_date
            """
        ).fetch_record_batch(65_536)
        for batch in reader:
            names = batch.schema.names
            columns = [batch.column(index).to_pylist() for index in range(len(names))]
            for values in zip(*columns, strict=True):
                row = dict(zip(names, values, strict=True))
                yield PanelSession(
                    symbol=str(row["symbol"]),
                    trade_date=_date(row["trade_date"]),
                    decision_at=_aware(row["decision_at"]),
                    available_at=_aware(row["available_at"]),
                    close=float(row["close"]),
                    share_multiplier=float(row.get("share_multiplier") or 1.0),
                    cash_per_share=float(row.get("cash_per_share") or 0.0),
                    snapshot_ids=tuple(
                        str(row[name])
                        for name in (
                            "daily_snapshot_id",
                            "corporate_action_snapshot_id",
                        )
                        if row.get(name)
                    ),
                )
    finally:
        con.close()


def _capacity_evidence(
    events: Sequence[Mapping[str, Any]], outcomes: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    event_by_id = {str(row["candidate_id"]): row for row in events}
    entries = [row for row in outcomes if row.get("entry_at") is not None]
    closed = [row for row in outcomes if row.get("status") == "FILLED"]
    participation = [
        float(row["entry_participation"])
        for row in entries
        if row.get("entry_participation") is not None
    ]
    sized_cash: dict[str, float] = {}
    for row in entries:
        raw = float(row["entry_cash"])
        raw_participation = float(row["entry_participation"])
        liquidity_cash = raw * 0.10 / raw_participation if raw_participation > 0 else 0.0
        sized_cash[str(row["signal_id"])] = min(500_000.0, liquidity_cash)
    executable = {
        signal_id for signal_id, cash in sized_cash.items() if cash >= 10_000.0
    }
    schedule_rows = sorted(
        (
            row
            for row in closed
            if str(row["signal_id"]) in executable
            and row.get("entry_at") is not None
            and row.get("exit_at") is not None
        ),
        key=lambda row: (str(row["entry_at"]), str(row["signal_id"])),
    )
    accepted: list[Mapping[str, Any]] = []
    active: list[Mapping[str, Any]] = []
    day_counts: defaultdict[date, int] = defaultdict(int)
    for row in schedule_rows:
        entry_at = datetime.fromisoformat(str(row["entry_at"]))
        active = [item for item in active if str(item["exit_at"]) > entry_at.isoformat()]
        industry = str(event_by_id[str(row["signal_id"])]["industry"])
        same_industry = sum(
            str(event_by_id[str(item["signal_id"])]["industry"]) == industry
            for item in active
        )
        if len(active) >= 50 or same_industry >= 10 or day_counts[entry_at.date()] >= 10:
            continue
        active.append(row)
        accepted.append(row)
        day_counts[entry_at.date()] += 1
    entry_rate = len(entries) / len(outcomes) if outcomes else 0.0
    closure_rate = len(closed) / len(outcomes) if outcomes else 0.0
    executable_rate = len(executable) / len(entries) if entries else 0.0
    gates = {
        "entry_fill_rate_at_least_95": entry_rate >= 0.95,
        "closure_rate_at_least_95": closure_rate >= 0.95,
        "liquidity_sized_cash_executable_at_least_95": executable_rate >= 0.95,
        "portfolio_schedule_nonempty": bool(accepted),
    }
    return {
        "gate": "PASS" if all(gates.values()) else "FAIL",
        "requested_events": len(outcomes),
        "entry_filled": len(entries),
        "closed": len(closed),
        "entry_fill_rate": entry_rate,
        "closure_rate": closure_rate,
        "nominal_participation_p95": (
            float(np.quantile(participation, 0.95)) if participation else None
        ),
        "nominal_participation_max": max(participation, default=None),
        "liquidity_sized_executable": len(executable),
        "liquidity_sized_executable_rate": executable_rate,
        "liquidity_sized_participation_target": 0.10,
        "portfolio_schedule_accepted": len(accepted),
        "portfolio_schedule_acceptance_rate": (
            len(accepted) / len(schedule_rows) if schedule_rows else 0.0
        ),
        "maximum_same_day_entries": max(day_counts.values(), default=0),
        "gates": gates,
    }


def _daily_inputs(
    feature_manifest: Mapping[str, Any],
) -> tuple[tuple[Path, ...], list[dict[str, Any]]]:
    raw = feature_manifest.get("daily_input_inventory")
    if not isinstance(raw, list) or len(raw) != 5:
        raise ValueError("stage 1 requires the exact 2018-2022 daily inventory")
    inventory: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or int(item.get("year", 0)) not in range(2018, 2023):
            raise ValueError("daily inventory contains a forbidden year")
        path = Path(str(item["absolute_path"])).resolve()
        if (
            not path.is_file()
            or path.stat().st_size != item["size"]
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"registered daily input changed: {path}")
        inventory.append(dict(item))
    inventory.sort(key=lambda item: int(item["year"]))
    return tuple(Path(str(item["absolute_path"])) for item in inventory), inventory


def _execution_inputs(
    config: MarkupRetestConfig,
) -> tuple[tuple[Path, ...], list[dict[str, Any]]]:
    registry = _object(REGISTRY.resolve())
    asset = next(
        item for item in registry["assets"] if item["asset_id"] == config.assets.minute_asset_id
    )
    manifest_path = Path(str(asset["lineage"]["manifest_path"])).resolve()
    if _sha256(manifest_path) != asset["lineage"]["manifest_sha256"]:
        raise ValueError("CY-008 registered manifest changed")
    manifest = _object(manifest_path)
    root = Path(str(manifest["root"])).resolve()
    inventory_by_path = {
        str(item["path"]): item for item in manifest["files"] if isinstance(item, dict)
    }
    inventory: list[dict[str, Any]] = []
    for year in (2020, 2021, 2022):
        relative = f"execution_5m/partition_year={year}/data_0.parquet"
        item = inventory_by_path[relative]
        path = root / relative
        if (
            not path.is_file()
            or path.stat().st_size != item["size"]
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"registered execution input changed: {path}")
        inventory.append(
            {
                "year": year,
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": item["sha256"],
            }
        )
    return tuple(Path(item["path"]) for item in inventory), inventory


def _protocol_chain() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    protocol = _object(PROTOCOL.resolve())
    addenda = [_object(path.resolve()) for path in ADDENDA]
    if protocol.get("status") != "PREREGISTERED":
        raise ValueError("stage 1 protocol is not preregistered")
    previous = None
    for item in addenda:
        if (
            item.get("protocol_event_id") != protocol.get("event_id")
            or item.get("holdout_outcomes_observed") is not False
            or (previous is not None and item.get("prior_addendum_event_id") != previous)
        ):
            raise ValueError("stage 1 addendum chain changed")
        previous = item["event_id"]
    return protocol, addenda


def _assert_single_run_budget(entries: Sequence[LedgerEntry], run_id: str) -> None:
    starts = [item for item in entries if item.event_type == "CHIP_INCREMENTAL_STAGE1_STARTED"]
    if any(item.payload.get("run_id") != run_id for item in starts) or len(starts) > 1:
        raise ValueError("the single stage-1 outcome run budget is already consumed")
    completions = [
        item for item in entries if item.event_type == "CHIP_INCREMENTAL_STAGE1_COMPLETE"
    ]
    if any(item.payload.get("run_id") != run_id for item in completions) or len(completions) > 1:
        raise ValueError("unexpected stage-1 completion ledger state")


def _outcome_row(outcome: FixedHorizonTrade) -> dict[str, Any]:
    row = asdict(outcome)
    row["signal_date"] = outcome.signal_date.isoformat()
    for name in ("entry_at", "exit_at"):
        value = row[name]
        row[name] = value.isoformat() if value is not None else None
    if outcome.scheduled_exit_date is not None:
        row["scheduled_exit_date"] = outcome.scheduled_exit_date.isoformat()
    row["reason_codes"] = list(outcome.reason_codes)
    row["snapshot_ids"] = list(outcome.snapshot_ids)
    return row


def _write_part(
    target: Path,
    run_id: str,
    expected: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    seconds: float,
) -> None:
    expected_ids = {str(row["candidate_id"]) for row in expected}
    actual_ids = {str(row["signal_id"]) for row in outcomes}
    if len(outcomes) != len(actual_ids) or actual_ids != expected_ids:
        raise ValueError("outcome worker coverage mismatch")
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    temporary.mkdir(parents=True)
    path = temporary / "outcomes.parquet"
    pq.write_table(pa.Table.from_pylist(list(outcomes)), path, compression="zstd")
    _write(
        temporary / "manifest.json",
        {
            "status": "COMPLETE",
            "run_id": run_id,
            "expected_event_hash": _digest("|".join(sorted(expected_ids))),
            "outcomes": len(outcomes),
            "outcomes_sha256": _sha256(path),
            "wall_seconds": seconds,
            "holdout_accessed": False,
        },
    )
    if target.exists():
        raise FileExistsError(f"outcome part appeared concurrently: {target}")
    temporary.replace(target)


def _valid_part(
    target: Path, run_id: str, expected: Sequence[Mapping[str, Any]]
) -> bool:
    manifest_path = target / "manifest.json"
    data_path = target / "outcomes.parquet"
    if not manifest_path.is_file() or not data_path.is_file():
        return False
    manifest = _object(manifest_path)
    expected_ids = {str(row["candidate_id"]) for row in expected}
    return (
        manifest.get("status") == "COMPLETE"
        and manifest.get("run_id") == run_id
        and manifest.get("expected_event_hash")
        == _digest("|".join(sorted(expected_ids)))
        and manifest.get("outcomes") == len(expected_ids)
        and manifest.get("outcomes_sha256") == _sha256(data_path)
    )


def _append_once(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != payload["event_id"]:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError("stage-1 ledger collision")
        return entry
    return ledger.append(event_type, payload)


def _inventory(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.resolve().relative_to(STAGE_ROOT.resolve())),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(set(paths))
    ]


def _write_parquet_immutable(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    table = pa.Table.from_pylist([dict(row) for row in rows])
    if path.exists():
        existing = pq.read_table(path)
        if not existing.equals(table):
            raise FileExistsError(f"immutable parquet differs: {path}")
        return
    temporary = path.with_suffix(".tmp.parquet")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)


def _write_immutable(path: Path, value: Mapping[str, Any]) -> None:
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable stage-1 artifact differs: {path}")
        return
    path.write_text(raw, encoding="utf-8")


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _aware(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=CN_TZ) if parsed.tzinfo is None else parsed


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(paths: Sequence[Path]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _brief(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": payload["status"],
        "run_id": payload["run_id"],
        "terminal_decision": payload["terminal_decision"],
        "passing_modules": payload["passing_modules"],
        "stage_2_authorized": payload["stage_2_authorized"],
        "maximum_physical_data_year": payload["maximum_physical_data_year"],
        "holdout_outcomes_observed": payload["holdout_outcomes_observed"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
