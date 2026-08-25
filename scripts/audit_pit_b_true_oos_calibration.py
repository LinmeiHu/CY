#!/usr/bin/env python3
"""Audit PIT-B calibration on two strictly ordered 2020--2022 folds."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cyq_game.data import (
    DataAssetRegistry,
    DataOperation,
    InputSnapshotManifest,
    PITBDailyStore,
)
from cyq_game.portfolio.sizing import CalibratedForecast
from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage

PROTOCOL_VERSION = "PIT_B_TRUE_OOS_CALIBRATION_PROTOCOL_V3"
_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class FoldSpec:
    fold_id: int
    name: str
    refit_dates: frozenset[date]
    calibration_train_dates: frozenset[date]
    purge_dates: frozenset[date]
    evaluation_dates: frozenset[date]
    embargo_dates: frozenset[date]
    decision_at: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/markup_retest_main_chinext_2020_2023_v1.yaml"),
    )
    parser.add_argument(
        "--input-snapshot",
        type=Path,
        default=Path(
            "data/input_snapshots/"
            "CYQ-PIT-B-DAILY-CALIBRATION-2018-2022-20260824-V1.json"
        ),
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        default=Path(
            "data/registered_inputs/"
            "CY-019-MARKUP-RETEST-MAIN-CHINEXT-2020-2023-V11/lineage/symbols.txt"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "pit_b_true_oos_calibration_v3.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(target.with_suffix(".lock")):
        return _run(args, config, target)


def _run(
    args: argparse.Namespace,
    config: MarkupRetestConfig,
    target: Path,
) -> int:
    registry = DataAssetRegistry.load(config.registry_path)
    input_snapshot = InputSnapshotManifest.load(args.input_snapshot, registry=registry)
    authorization = input_snapshot.authorize(
        DataOperation.STATE_GENERATION,
        registry=registry,
    )
    _assert_development_lock(config, authorization.scope_end)
    symbols = _read_symbols(args.symbols_file)
    source_inventory = _source_inventory(
        config=config,
        input_snapshot=input_snapshot,
        symbols_file=args.symbols_file.resolve(),
    )
    ledger = TrialLedger(config.trial_ledger)
    invalidation_entry = _append_idempotent(
        ledger,
        "PIT_B_CALIBRATION_P0_INVALIDATED",
        _invalidation_payload(config),
    )
    v2_invalidation_entry = _append_idempotent(
        ledger,
        "PIT_B_TRUE_OOS_CALIBRATION_V2_INVALIDATED",
        _v2_invalidation_payload(config),
    )
    protocol = _protocol_payload(
        config=config,
        input_snapshot=input_snapshot,
        symbols=symbols,
        source_inventory=source_inventory,
    )
    protocol_entry = _append_idempotent(
        ledger,
        PROTOCOL_VERSION,
        protocol,
    )

    metadata_path = target.parent / "pit_b_true_oos_calibration_v3_metadata.sqlite3"
    store = PITBDailyStore(
        metadata_path,
        binding=input_snapshot.binding("daily_pit_b"),
        authorization=authorization,
    )
    try:
        store.initialize()
        active_files = tuple(store.activated_daily_files)
        _assert_no_post_2022_partition(active_files)
        all_dates = store.trading_dates_as_of(
            date(2020, 1, 1),
            date(2022, 12, 30),
            _at_end_of_day(date(2022, 12, 31)),
        )
        folds = _build_folds(all_dates)
        fold_reports = [
            _evaluate_fold(store=store, symbols=symbols, spec=spec)
            for spec in folds
        ]
    finally:
        store.close()

    gate_checks = {
        "two_strict_later_folds": len(fold_reports) == 2
        and all(bool(item["strict_order_pass"]) for item in fold_reports),
        "five_session_purge_each_fold": all(
            int(item["purge_days"]) == 5 for item in fold_reports
        ),
        "actual_ece_brier_present": all(
            int(item["actual_metric_symbol_count"]) > 0
            and item["weighted_actual_ece"] is not None
            and item["weighted_model_brier"] is not None
            and item["weighted_baseline_brier"] is not None
            for item in fold_reports
        ),
        "fallback_fail_closed": all(
            bool(item["fallback_contract_pass"]) for item in fold_reports
        ),
        "labels_end_by_2022": all(
            item["maximum_evaluation_label_date"] is None
            or date.fromisoformat(str(item["maximum_evaluation_label_date"]))
            <= date(2022, 12, 30)
            for item in fold_reports
        ),
        "physical_2023_partition_excluded": all(
            (_partition_year(path) or 0) <= 2022 for path in active_files
        ),
        "holdout_accessed": False,
    }
    status = "PASS" if all(
        value is True
        for key, value in gate_checks.items()
        if key != "holdout_accessed"
    ) else "FAIL"
    report: dict[str, Any] = {
        "schema_version": 2,
        "status": status,
        "protocol_version": PROTOCOL_VERSION,
        "protocol_run_id": protocol["run_id"],
        "registered_at": protocol_entry.recorded_at,
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "input_snapshot": {
            "path": str(input_snapshot.path),
            "manifest_id": input_snapshot.manifest_id,
            "sha256": input_snapshot.sha256,
            "scope_start": input_snapshot.scope_start.isoformat(),
            "scope_end": input_snapshot.scope_end.isoformat(),
        },
        "universe": {
            "symbols_file": str(args.symbols_file.resolve()),
            "symbols_file_sha256": _sha256_file(args.symbols_file.resolve()),
            "symbol_count": len(symbols),
        },
        "physical_activation": {
            "daily_files": [_file_record(path) for path in active_files],
            "partition_years": sorted(
                year
                for path in active_files
                if (year := _partition_year(path)) is not None
            ),
            "post_2022_file_count": sum(
                1 for path in active_files if (_partition_year(path) or 0) > 2022
            ),
        },
        "ledger_preregistration": {
            "p0_invalidation": _ledger_record(invalidation_entry),
            "v2_audit_invalidation": _ledger_record(v2_invalidation_entry),
            "true_oos_protocol_v3": _ledger_record(protocol_entry),
            "occurred_before_return_metrics": True,
        },
        "folds": fold_reports,
        "aggregate": _aggregate_folds(fold_reports),
        "gate_checks": gate_checks,
        "interpretation": {
            "p0_gate_meaning": (
                "The calibration implementation produced real later-fold ECE/Brier "
                "evidence and failed closed per symbol."
            ),
            "kelly_authorization_scope": (
                "Only symbols reported as oos_valid in the relevant fold may pass the "
                "forecast calibration precondition; this report does not authorize an "
                "EdgeCard, order, live access, or strategy parameter freeze."
            ),
            "zero_or_low_valid_symbol_count_policy": (
                "Do not relax ECE/Brier/sample gates; affected symbols remain blocked."
            ),
        },
        "source_inventory": source_inventory,
        "holdout_lock": {
            "year": 2023,
            "accessed": False,
            "maximum_queried_trade_date": "2022-12-30",
            "maximum_evaluation_label_date": max(
                str(item["maximum_evaluation_label_date"])
                for item in fold_reports
                if item["maximum_evaluation_label_date"] is not None
            ),
            "freeze_manifest_exists": config.freeze_manifest.exists(),
        },
    }
    report_sha256 = _write_immutable_json(target, report)
    completion = {
        "event_id": hashlib.sha256(
            f"{protocol['run_id']}|{report_sha256}|COMPLETE".encode()
        ).hexdigest(),
        "run_id": protocol["run_id"],
        "protocol_version": PROTOCOL_VERSION,
        "status": status,
        "manifest_path": str(target),
        "manifest_sha256": report_sha256,
        "fold_count": len(fold_reports),
        "kelly_authorized_symbol_fold_pairs": sum(
            int(item["oos_valid_symbol_count"]) for item in fold_reports
        ),
        "holdout_accessed": False,
    }
    completion_entry = _append_idempotent(
        ledger,
        "PIT_B_TRUE_OOS_CALIBRATION_GATE_COMPLETE",
        completion,
    )
    print(
        json.dumps(
            {
                "status": status,
                "manifest": str(target),
                "manifest_sha256": report_sha256,
                "folds": [
                    {
                        "name": item["name"],
                        "actual_metric_symbol_count": item[
                            "actual_metric_symbol_count"
                        ],
                        "oos_valid_symbol_count": item["oos_valid_symbol_count"],
                        "weighted_actual_ece": item["weighted_actual_ece"],
                        "weighted_model_brier": item["weighted_model_brier"],
                        "weighted_baseline_brier": item[
                            "weighted_baseline_brier"
                        ],
                    }
                    for item in fold_reports
                ],
                "completion_ledger_sequence": completion_entry.sequence,
                "holdout_accessed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if status == "PASS" else 1


def _build_folds(all_dates: Sequence[date]) -> tuple[FoldSpec, FoldSpec]:
    by_year = {
        year: tuple(item for item in all_dates if item.year == year)
        for year in (2020, 2021, 2022)
    }
    for year, dates in by_year.items():
        if len(dates) < 40:
            raise ValueError(f"PIT-B calibration year {year} has too few trading dates")
    fold_1 = FoldSpec(
        fold_id=1,
        name="FIT_2020_EVALUATE_2021",
        refit_dates=frozenset(by_year[2020] + by_year[2021]),
        calibration_train_dates=frozenset(by_year[2020]),
        purge_dates=frozenset(by_year[2021][:5]),
        evaluation_dates=frozenset(by_year[2021][5:-5]),
        embargo_dates=frozenset(by_year[2021][-5:]),
        decision_at=_at_end_of_day(date(2022, 1, 1)),
    )
    fold_2 = FoldSpec(
        fold_id=2,
        name="FIT_2020_2021_EVALUATE_2022",
        refit_dates=frozenset(by_year[2020] + by_year[2021] + by_year[2022]),
        calibration_train_dates=frozenset(by_year[2020] + by_year[2021]),
        purge_dates=frozenset(by_year[2022][:5]),
        evaluation_dates=frozenset(by_year[2022][5:-5]),
        embargo_dates=frozenset(by_year[2022][-5:]),
        decision_at=_at_end_of_day(date(2022, 12, 31)),
    )
    for spec in (fold_1, fold_2):
        ordered_purge = sorted(spec.purge_dates)
        if len(ordered_purge) != 5:
            raise ValueError(f"{spec.name} must have exactly five purge sessions")
        if not (
            max(spec.calibration_train_dates)
            < min(spec.purge_dates)
            <= max(spec.purge_dates)
            < min(spec.evaluation_dates)
            <= max(spec.evaluation_dates)
            < min(spec.embargo_dates)
        ):
            raise ValueError(f"{spec.name} fold ordering is invalid")
    return fold_1, fold_2


def _evaluate_fold(
    *,
    store: PITBDailyStore,
    symbols: Sequence[str],
    spec: FoldSpec,
) -> dict[str, Any]:
    forecasts = store.calibrate_forecasts(
        symbols,
        set(spec.refit_dates),
        spec.decision_at,
        calibration_train_dates=set(spec.calibration_train_dates),
        evaluation_dates=set(spec.evaluation_dates),
        purge_dates=set(spec.purge_dates),
        embargo_dates=set(spec.embargo_dates),
        fold_id=spec.fold_id,
    )
    if set(forecasts) != set(symbols):
        raise ValueError(f"{spec.name} forecast universe mismatch")
    values = tuple(forecasts.values())
    evaluated = tuple(item for item in values if item.calibration_brier is not None)
    valid = tuple(item for item in values if item.valid)
    unauthorized_true = tuple(
        item for item in values if item.out_of_sample and not item.valid
    )
    reason_counts = Counter(
        item.calibration_gate_reason or "OOS_VALID" for item in values
    )
    labels = tuple(
        item.evaluation_label_end
        for item in values
        if item.evaluation_label_end is not None
    )
    snapshot_ids = sorted(
        item.calibration_snapshot_id
        for item in values
        if item.calibration_snapshot_id is not None
    )
    code_hashes = sorted(
        {
            item.calibration_code_sha256
            for item in values
            if item.calibration_code_sha256 is not None
        }
    )
    strict_order_pass = (
        max(spec.calibration_train_dates)
        < min(spec.purge_dates)
        <= max(spec.purge_dates)
        < min(spec.evaluation_dates)
        <= max(spec.evaluation_dates)
        < min(spec.embargo_dates)
    )
    return {
        "fold_id": spec.fold_id,
        "name": spec.name,
        "decision_at": spec.decision_at.isoformat(),
        "calibration_training_start": min(spec.calibration_train_dates).isoformat(),
        "calibration_training_end": max(spec.calibration_train_dates).isoformat(),
        "calibration_training_origin_days": len(spec.calibration_train_dates),
        "purge_start": min(spec.purge_dates).isoformat(),
        "purge_end": max(spec.purge_dates).isoformat(),
        "purge_days": len(spec.purge_dates),
        "evaluation_start": min(spec.evaluation_dates).isoformat(),
        "evaluation_end": max(spec.evaluation_dates).isoformat(),
        "evaluation_origin_days": len(spec.evaluation_dates),
        "embargo_start": min(spec.embargo_dates).isoformat(),
        "embargo_end": max(spec.embargo_dates).isoformat(),
        "embargo_days": len(spec.embargo_dates),
        "strict_order_pass": strict_order_pass,
        "universe_symbol_count": len(symbols),
        "actual_metric_symbol_count": len(evaluated),
        "oos_valid_symbol_count": len(valid),
        "oos_valid_symbol_fraction": len(valid) / len(symbols),
        "actual_metric_symbol_fraction": len(evaluated) / len(symbols),
        "unauthorized_out_of_sample_true_count": len(unauthorized_true),
        "fallback_contract_pass": len(unauthorized_true) == 0
        and all(item.out_of_sample == item.valid for item in values),
        "reason_counts": dict(sorted(reason_counts.items())),
        "calibration_training_sample_total": sum(
            item.training_sample_size for item in values
        ),
        "evaluation_sample_total": sum(item.sample_size for item in values),
        "weighted_actual_ece": _weighted_metric(
            evaluated, "calibration_error"
        ),
        "weighted_model_brier": _weighted_metric(
            evaluated, "calibration_brier"
        ),
        "weighted_baseline_brier": _weighted_metric(
            evaluated, "baseline_brier"
        ),
        "weighted_calibration_train_occurrence_rate": _weighted_metric(
            evaluated, "calibration_train_occurrence_rate"
        ),
        "weighted_evaluation_occurrence_rate": _weighted_metric(
            evaluated, "evaluation_occurrence_rate"
        ),
        "maximum_evaluation_label_date": (
            max(labels).isoformat() if labels else None
        ),
        "calibration_snapshot_count": len(snapshot_ids),
        "calibration_snapshot_set_sha256": _sha256_text("\n".join(snapshot_ids)),
        "calibration_code_sha256": code_hashes,
    }


def _aggregate_folds(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "symbol_fold_pairs": sum(int(item["universe_symbol_count"]) for item in folds),
        "actual_metric_symbol_fold_pairs": sum(
            int(item["actual_metric_symbol_count"]) for item in folds
        ),
        "oos_valid_symbol_fold_pairs": sum(
            int(item["oos_valid_symbol_count"]) for item in folds
        ),
        "unauthorized_out_of_sample_true_count": sum(
            int(item["unauthorized_out_of_sample_true_count"]) for item in folds
        ),
        "kelly_policy": "PER_SYMBOL_RELEVANT_FOLD_ONLY",
    }


def _weighted_metric(
    forecasts: Sequence[CalibratedForecast],
    field: str,
) -> float | None:
    weighted = 0.0
    samples = 0
    for forecast in forecasts:
        value = getattr(forecast, field)
        if value is None or forecast.sample_size <= 0:
            continue
        weighted += float(value) * forecast.sample_size
        samples += forecast.sample_size
    return weighted / samples if samples else None


def _assert_development_lock(
    config: MarkupRetestConfig,
    scope_end: date,
) -> None:
    if scope_end > date(2022, 12, 30):
        raise ValueError("P0 calibration activation scope may not include 2023")
    if config.freeze_manifest.exists():
        raise ValueError("P0 correction must precede every strategy freeze")
    for name in ("panel", "signals", "labels", "validation"):
        if (config.outputs.root / name / StrategyStage.RESEALED.value).exists():
            raise ValueError(f"2023 resealed artifact already exists under {name}")
    entries = TrialLedger(config.trial_ledger).read_verified()
    event_types = {entry.event_type for entry in entries}
    required = {
        "ENTRY_SELECTION_PROTOCOL_INVALIDATED",
        "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2",
    }
    if not required.issubset(event_types):
        raise ValueError("entry protocol invalidation/preregistration is incomplete")
    for entry in entries:
        if entry.payload.get("holdout_accessed") is True:
            raise ValueError(
                f"ledger already records holdout access at sequence {entry.sequence}"
            )


def _assert_no_post_2022_partition(paths: Sequence[Path]) -> None:
    post = [path for path in paths if (_partition_year(path) or 0) > 2022]
    if post:
        raise ValueError(f"P0 activation exposed post-2022 files: {post}")


def _invalidation_payload(config: MarkupRetestConfig) -> dict[str, Any]:
    identity = f"PIT_B_CALIBRATION_P0_INVALIDATED|{config.sha256}|V1"
    return {
        "event_id": hashlib.sha256(identity.encode()).hexdigest(),
        "config_sha256": config.sha256,
        "old_calibration_status": "INVALIDATED",
        "formal_oos_eligible": False,
        "reason_codes": [
            "TRAINING_STATISTIC_WAS_MARKED_OUT_OF_SAMPLE",
            "FALLBACK_COULD_AUTHORIZE_OUT_OF_SAMPLE",
            "CALIBRATION_ERROR_WAS_NOT_ACTUAL_EVALUATION_ERROR",
            "SPARSE_ORIGIN_LEAD_CHANGED_THE_FIVE_SESSION_HORIZON",
            "NO_TRUE_LATER_FOLD_ECE_BRIER_BASELINE_COMPARISON",
        ],
        "blocked_downstream": [
            "KELLY",
            "EDGECARD",
            "FINAL_PARAMETER_FREEZE",
            "2023_HOLDOUT_ACCESS",
        ],
        "holdout_accessed": False,
    }


def _v2_invalidation_payload(config: MarkupRetestConfig) -> dict[str, Any]:
    path = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "pit_b_true_oos_calibration_v2.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("PIT-B v2 audit must be a JSON object")
    unauthorized = int(
        payload.get("aggregate", {}).get("unauthorized_out_of_sample_true_count", -1)
    )
    if payload.get("status") != "FAIL" or unauthorized <= 0:
        raise ValueError("PIT-B v2 audit does not match the fail-closed defect evidence")
    digest = _sha256_file(path)
    identity = f"PIT_B_TRUE_OOS_CALIBRATION_V2_INVALIDATED|{config.sha256}|{digest}"
    return {
        "event_id": hashlib.sha256(identity.encode()).hexdigest(),
        "config_sha256": config.sha256,
        "superseded_protocol_version": "PIT_B_TRUE_OOS_CALIBRATION_PROTOCOL_V2",
        "superseded_manifest": _file_record(path),
        "superseded_status": "DIAGNOSTIC_FAIL",
        "formal_gate_eligible": False,
        "reason": "OUT_OF_SAMPLE_TRUE_SURVIVED_WITH_INCOMPLETE_FOLD_END_COVERAGE",
        "unauthorized_out_of_sample_true_count": unauthorized,
        "correction": (
            "Require each symbol's last available evaluation label date to cover "
            "the preregistered global evaluation end before out_of_sample may be true."
        ),
        "holdout_accessed": False,
    }


def _protocol_payload(
    *,
    config: MarkupRetestConfig,
    input_snapshot: InputSnapshotManifest,
    symbols: Sequence[str],
    source_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    run_id = hashlib.sha256(
        (
            f"{PROTOCOL_VERSION}|{config.sha256}|{input_snapshot.sha256}|"
            f"{_sha256_text(chr(10).join(symbols))}"
        ).encode()
    ).hexdigest()
    return {
        "event_id": hashlib.sha256(f"{run_id}|PROTOCOL".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "config_sha256": config.sha256,
        "input_manifest_id": input_snapshot.manifest_id,
        "input_manifest_sha256": input_snapshot.sha256,
        "universe_symbol_count": len(symbols),
        "development_period": ["2020-01-01", "2022-12-30"],
        "folds": [
            {
                "fit_origins": "2020 trading sessions",
                "purge": "first five 2021 trading sessions",
                "evaluation_origins": "remaining 2021 excluding final five sessions",
                "embargo": "final five 2021 trading sessions",
            },
            {
                "fit_origins": "2020-2021 trading sessions",
                "purge": "first five 2022 trading sessions",
                "evaluation_origins": "remaining 2022 excluding final five sessions",
                "embargo": "final five 2022 trading sessions",
            },
        ],
        "label_contract": {
            "horizon": "FIFTH_FULL_PER_SYMBOL_TRADING_SESSION",
            "construct_before_origin_filter": True,
            "origin_hard_valid_required": True,
            "origin_corporate_action_count_must_equal": 0,
            "corporate_actions_in_next_five_sessions_must_equal": 0,
            "label_must_be_available_before_decision": True,
        },
        "per_symbol_gate": {
            "minimum_fit_samples": 30,
            "minimum_evaluation_samples": 30,
            "both_classes_required": True,
            "actual_ece_maximum": 0.05,
            "actual_model_brier_strictly_below_pooled_occurrence_baseline": True,
            "invalid_or_missing_evidence_out_of_sample": False,
        },
        "audit_gate": {
            "every_symbol_returns_valid_evidence_or_fail_closed_reason": True,
            "no_minimum_kelly_authorized_fraction": True,
            "reason": "Calibration failure blocks the symbol; thresholds are not relaxed.",
        },
        "holdout_lock": {
            "year": 2023,
            "accessed": False,
            "physical_partition_excluded": True,
            "freeze_before_gate_complete": "FAIL_CLOSED",
        },
        "source_inventory": source_inventory,
        "holdout_accessed": False,
    }


def _source_inventory(
    *,
    config: MarkupRetestConfig,
    input_snapshot: InputSnapshotManifest,
    symbols_file: Path,
) -> dict[str, Any]:
    return {
        "config": _file_record(config.path),
        "registry": _file_record(config.registry_path),
        "input_snapshot": _file_record(input_snapshot.path),
        "symbols": _file_record(symbols_file),
        "code": [
            _file_record(Path("src/cyq_game/data/pit_b_store.py").resolve()),
            _file_record(Path("src/cyq_game/data/pit.py").resolve()),
            _file_record(Path("src/cyq_game/portfolio/sizing.py").resolve()),
            _file_record(Path("src/cyq_game/backtest/engine.py").resolve()),
            _file_record(Path(__file__).resolve()),
        ],
    }


def _read_symbols(path: Path) -> tuple[str, ...]:
    resolved = path.resolve()
    symbols = tuple(
        line.strip() for line in resolved.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    if len(symbols) != 4_651 or len(set(symbols)) != len(symbols):
        raise ValueError("registered main/ChiNext universe must contain 4,651 unique symbols")
    return symbols


def _append_idempotent(
    ledger: TrialLedger,
    event_type: str,
    payload: Mapping[str, Any],
) -> LedgerEntry:
    event_id = str(payload["event_id"])
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != event_id:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError(f"trial ledger event collision: {event_id}")
        return entry
    return ledger.append(event_type, payload)


def _ledger_record(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "event_type": entry.event_type,
        "event_id": entry.payload.get("event_id"),
        "sequence": entry.sequence,
        "entry_hash": entry.entry_hash,
    }


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"
    digest = _sha256_text(raw)
    if path.exists():
        if path.read_text(encoding="utf-8") != raw:
            raise FileExistsError(f"immutable P0 calibration report differs: {path}")
        return digest
    temporary = path.with_suffix(f".{digest[:12]}.tmp")
    temporary.write_text(raw, encoding="utf-8")
    temporary.replace(path)
    return digest


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _partition_year(path: Path) -> int | None:
    for part in reversed(path.parts):
        for prefix in ("partition_year=", "year="):
            if not part.startswith(prefix):
                continue
            value = part.removeprefix(prefix).split(".", maxsplit=1)[0]
            if len(value) == 4 and value.isdigit():
                return int(value)
    return None


def _at_end_of_day(value: date) -> datetime:
    return datetime.combine(value, time(23, 59, 59), tzinfo=_SHANGHAI)


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("P0 calibration audit is already running") from error
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    raise SystemExit(main())
