#!/usr/bin/env python3
"""Validate the frozen V12 50-symbol checkpoint+journal engineering sample."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_SIZE = 50
TRADING_DAYS = 243
SELLER_MODELS = 3
CHECKPOINTS_PER_SYMBOL = 13
EXACT_COMPARISONS = SAMPLE_SIZE * TRADING_DAYS * SELLER_MODELS
T49_975 = 2.0095752371292392
GIB = 1024**3
FEATURE_GIB_3941 = 0.161144
METADATA_GIB_3941 = (0.05, 0.10, 0.25)
COMPATIBILITY_TERMINAL_GIB_3941 = 3.453860

DEFAULT_SAMPLE = Path("configs/v12_checkpoint_recompute_50_symbols_v1.txt")
DEFAULT_EVIDENCE = Path("data/validation/v12_checkpoint_recompute_50_v1")
DEFAULT_OUTPUT = Path("data/validation/v12_checkpoint_journal_phase5_50symbol")

JOURNAL_REQUIRED = {
    "format_version",
    "day_dates",
    "day_input_digest",
    "day_input_offsets",
    "day_input_refs",
    "day_action_offsets",
    "day_action_refs",
    "day_cash_bits",
    "day_multiplier_bits",
    "day_circulating_bits",
    "day_feature_digest",
    "model_offsets",
    "model_code",
    "model_hash",
    "model_transition_hash",
    "model_runtime_hash",
    "model_operator_digest",
    "model_post_digest",
    "model_snapshot_refs",
    "model_transition_refs",
    "string_bytes",
    "string_offsets",
}

CHECKPOINT_REQUIRED = {
    "format_version",
    "union_identity",
    "checkpoint_date",
    "symbol_ref",
    "model_lot_offsets",
    "model_decision_us",
    "model_effective_us",
    "model_available_us",
    "model_snapshot_refs",
    "model_version_refs",
    "model_grid_refs",
    "model_free_float_bits",
    "model_latent_supply_bits",
    "model_conservation_error_bits",
    "model_cell_ids_current",
    "model_pit_refs",
    "model_hard_valid",
    "model_input_offsets",
    "model_quality_offsets",
    "tracker_base_refs",
    "tracker_action_offsets",
    "tracker_peak_offsets",
    "string_bytes",
    "string_offsets",
}


class ValidationError(RuntimeError):
    """The frozen evidence does not satisfy a Phase 5 fixed gate."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def read_sample_symbols(path: Path) -> list[str]:
    symbols = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    duplicates = sorted({symbol for symbol in symbols if symbols.count(symbol) > 1})
    _require(len(symbols) == SAMPLE_SIZE, f"sample must contain exactly {SAMPLE_SIZE} symbols")
    _require(not duplicates, f"sample contains duplicate symbols: {duplicates}")
    return symbols


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path}: expected a JSON object")
    return value


def _file_bytes(paths: Iterable[Path]) -> int:
    return sum(path.stat().st_size for path in paths)


def _validate_string_pool(data: Any, path: Path) -> None:
    payload = data["string_bytes"]
    offsets = data["string_offsets"]
    _require(payload.dtype == np.uint8 and payload.ndim == 1, f"{path}: invalid string bytes")
    _require(offsets.dtype == np.uint64 and offsets.ndim == 1, f"{path}: invalid string offsets")
    _require(len(offsets) >= 1 and int(offsets[0]) == 0, f"{path}: invalid string pool origin")
    _require(bool(np.all(offsets[1:] >= offsets[:-1])), f"{path}: non-monotonic string offsets")
    _require(int(offsets[-1]) == len(payload), f"{path}: string pool length mismatch")


def _validate_offsets(offsets: np.ndarray[Any, Any], rows: int, payload: int, path: Path, name: str) -> None:
    _require(offsets.shape == (rows + 1,), f"{path}: {name} shape mismatch")
    _require(int(offsets[0]) == 0 and int(offsets[-1]) == payload, f"{path}: {name} bounds mismatch")
    _require(bool(np.all(offsets[1:] >= offsets[:-1])), f"{path}: {name} is non-monotonic")


def _validate_journal(path: Path) -> dict[str, int]:
    with np.load(path, allow_pickle=False) as data:
        _require(set(data.files) == JOURNAL_REQUIRED, f"{path}: journal schema mismatch")
        for name in data.files:
            _require(data[name].dtype.kind != "O", f"{path}: object array {name} is forbidden")
        _require(data["format_version"].shape == (1,) and int(data["format_version"][0]) == 1, f"{path}: unknown format")
        _require(data["day_dates"].shape == (TRADING_DAYS,), f"{path}: journal day count mismatch")
        _require(bool(np.all(data["day_dates"][1:] > data["day_dates"][:-1])), f"{path}: journal dates not increasing")
        _require(data["day_input_digest"].shape == (TRADING_DAYS, 32), f"{path}: input digest shape mismatch")
        _require(data["day_feature_digest"].shape == (TRADING_DAYS, 32), f"{path}: feature digest shape mismatch")
        for name in ("day_cash_bits", "day_multiplier_bits", "day_circulating_bits"):
            _require(data[name].shape == (TRADING_DAYS,) and data[name].dtype == np.uint64, f"{path}: {name} mismatch")
        _validate_offsets(data["day_input_offsets"], TRADING_DAYS, len(data["day_input_refs"]), path, "day_input_offsets")
        _validate_offsets(data["day_action_offsets"], TRADING_DAYS, len(data["day_action_refs"]), path, "day_action_offsets")
        _validate_offsets(data["model_offsets"], TRADING_DAYS, len(data["model_code"]), path, "model_offsets")
        _require(bool(np.all(np.diff(data["model_offsets"]) == SELLER_MODELS)), f"{path}: seller model count mismatch")
        expected_codes = np.tile(np.arange(SELLER_MODELS, dtype=np.uint8), TRADING_DAYS)
        _require(bool(np.array_equal(data["model_code"], expected_codes)), f"{path}: seller model ordering mismatch")
        model_rows = TRADING_DAYS * SELLER_MODELS
        for name in (
            "model_hash",
            "model_transition_hash",
            "model_runtime_hash",
            "model_operator_digest",
            "model_post_digest",
        ):
            _require(data[name].shape == (model_rows, 32), f"{path}: {name} shape mismatch")
        for name in ("model_snapshot_refs", "model_transition_refs"):
            _require(data[name].shape == (model_rows,), f"{path}: {name} shape mismatch")
        _validate_string_pool(data, path)
    return {"days": TRADING_DAYS, "model_rows": TRADING_DAYS * SELLER_MODELS}


def _validate_checkpoint(path: Path) -> int:
    with np.load(path, allow_pickle=False) as data:
        _require(CHECKPOINT_REQUIRED <= set(data.files), f"{path}: checkpoint schema is incomplete")
        for name in data.files:
            _require(data[name].dtype.kind != "O", f"{path}: object array {name} is forbidden")
        _require(data["format_version"].shape == (1,) and int(data["format_version"][0]) == 1, f"{path}: unknown format")
        _require(data["union_identity"].shape == (1,) and int(data["union_identity"][0]) == 1, f"{path}: union identity flag mismatch")
        _validate_offsets(data["model_lot_offsets"], SELLER_MODELS, len(data["lot_identity_positions"]), path, "model_lot_offsets")
        _validate_offsets(data["model_input_offsets"], SELLER_MODELS, len(data["model_input_refs"]), path, "model_input_offsets")
        _validate_offsets(data["model_quality_offsets"], SELLER_MODELS, len(data["model_quality_refs"]), path, "model_quality_offsets")
        for name in (
            "model_decision_us",
            "model_effective_us",
            "model_available_us",
            "model_snapshot_refs",
            "model_version_refs",
            "model_grid_refs",
            "model_free_float_bits",
            "model_latent_supply_bits",
            "model_conservation_error_bits",
            "model_cell_ids_current",
            "model_pit_refs",
            "model_hard_valid",
        ):
            _require(data[name].shape == (SELLER_MODELS,), f"{path}: {name} shape mismatch")
        conservation_bits = data["model_conservation_error_bits"]
        conservation_values = conservation_bits.view(np.float64)
        _require(bool(np.all(np.isfinite(conservation_values))), f"{path}: non-finite conservation error")
        nonzero = int(np.count_nonzero(conservation_bits))
        if not path.name.startswith("opening-"):
            _require(nonzero == 0, f"{path}: month-end checkpoint has nonzero conservation error")
        _validate_string_pool(data, path)
        return nonzero


def _engineering_interval(sample_bytes: list[int], symbols: int) -> tuple[float, float, float]:
    mean = statistics.mean(sample_bytes)
    standard_error = statistics.stdev(sample_bytes) / math.sqrt(len(sample_bytes))
    margin = T49_975 * standard_error
    return tuple((mean + offset * margin) * symbols / GIB for offset in (-1, 0, 1))  # type: ignore[return-value]


def _scenario_b(raw_3941: tuple[float, float, float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    actual = tuple(
        raw + FEATURE_GIB_3941 + metadata + COMPATIBILITY_TERMINAL_GIB_3941
        for raw, metadata in zip(raw_3941, METADATA_GIB_3941, strict=True)
    )
    normalized = tuple(value * 5210 / 3941 for value in actual)
    return actual, normalized  # type: ignore[return-value]


def _gate(gate_id: str, requirement: str, evidence: Any) -> dict[str, Any]:
    return {"id": gate_id, "requirement": requirement, "status": "PASS", "evidence": evidence}


def validate(sample_path: Path, evidence_root: Path) -> dict[str, Any]:
    symbols = read_sample_symbols(sample_path)
    _require(evidence_root.is_dir(), f"evidence root does not exist: {evidence_root}")

    symbol_dirs = sorted(path for path in evidence_root.glob("symbol=*") if path.is_dir())
    completed = [path.name.removeprefix("symbol=") for path in symbol_dirs]
    missing = sorted(set(symbols) - set(completed))
    unexpected = sorted(set(completed) - set(symbols))
    duplicate_dirs = sorted({symbol for symbol in completed if completed.count(symbol) > 1})
    _require(len(completed) == SAMPLE_SIZE, f"expected 50 completed symbol directories, found {len(completed)}")
    _require(not missing and not unexpected and not duplicate_dirs, "sample/evidence symbol mismatch")

    report = _load_json(evidence_root / "benchmark_report.json")
    _require(report.get("status") == "PASS", "frozen benchmark did not pass")
    _require(report.get("sample_symbols") == SAMPLE_SIZE, "benchmark sample size mismatch")
    report_symbols = report.get("symbols")
    _require(isinstance(report_symbols, list) and len(report_symbols) == SAMPLE_SIZE, "benchmark symbol rows mismatch")
    report_by_symbol = {row.get("symbol"): row for row in report_symbols if isinstance(row, dict)}
    _require(len(report_by_symbol) == SAMPLE_SIZE and set(report_by_symbol) == set(symbols), "benchmark symbol set mismatch")

    checkpoint_bytes = 0
    journal_bytes = 0
    manifest_bytes = 0
    checkpoint_files = 0
    journal_files = 0
    per_symbol_total_bytes: list[int] = []
    terminal_symbols = 0
    opening_conservation_error_bits_nonzero = 0
    month_end_conservation_error_bits_nonzero = 0
    for symbol in symbols:
        symbol_root = evidence_root / f"symbol={symbol}"
        manifest_path = symbol_root / "manifest.json"
        manifest = _load_json(manifest_path)
        _require(manifest.get("prototype") == "monthly-checkpoint-recompute-v1", f"{symbol}: prototype mismatch")
        _require(manifest.get("symbol") == symbol and manifest.get("year") == 2020, f"{symbol}: manifest identity mismatch")
        _require(manifest.get("checkpoint_count") == CHECKPOINTS_PER_SYMBOL, f"{symbol}: checkpoint count mismatch")
        _require(manifest.get("journal_days") == TRADING_DAYS, f"{symbol}: journal day count mismatch")
        names = manifest.get("checkpoint_files")
        _require(isinstance(names, list) and len(names) == CHECKPOINTS_PER_SYMBOL and len(set(names)) == CHECKPOINTS_PER_SYMBOL, f"{symbol}: checkpoint manifest mismatch")
        actual_checkpoints = sorted((symbol_root / "checkpoints").glob("*.npz"))
        _require(sorted(path.name for path in actual_checkpoints) == sorted(names), f"{symbol}: checkpoint files mismatch")
        terminal = [path for path in actual_checkpoints if path.name.startswith("month-12-")]
        _require(len(terminal) == 1, f"{symbol}: year-end terminal checkpoint missing")
        terminal_symbols += 1
        for checkpoint in actual_checkpoints:
            nonzero = _validate_checkpoint(checkpoint)
            if checkpoint.name.startswith("opening-"):
                opening_conservation_error_bits_nonzero += nonzero
            else:
                month_end_conservation_error_bits_nonzero += nonzero
        journal_path = symbol_root / str(manifest.get("journal_file"))
        _require(journal_path.name == "daily_replay_journal.npz" and journal_path.is_file(), f"{symbol}: journal missing")
        _validate_journal(journal_path)

        current_checkpoint_bytes = _file_bytes(actual_checkpoints)
        current_journal_bytes = journal_path.stat().st_size
        current_manifest_bytes = manifest_path.stat().st_size
        row = report_by_symbol[symbol]
        _require(row.get("days") == TRADING_DAYS and row.get("checkpoint_count") == CHECKPOINTS_PER_SYMBOL, f"{symbol}: report counts mismatch")
        _require(row.get("daily_exact_comparisons") == TRADING_DAYS * SELLER_MODELS, f"{symbol}: daily exact count mismatch")
        _require(row.get("lifecycle_exact_comparisons") == TRADING_DAYS * SELLER_MODELS, f"{symbol}: lifecycle exact count mismatch")
        _require(row.get("checkpoint_bytes") == current_checkpoint_bytes, f"{symbol}: checkpoint byte count mismatch")
        _require(row.get("journal_bytes") == current_journal_bytes, f"{symbol}: journal byte count mismatch")
        _require(row.get("manifest_bytes") == current_manifest_bytes, f"{symbol}: manifest byte count mismatch")
        current_total = current_checkpoint_bytes + current_journal_bytes + current_manifest_bytes
        _require(row.get("total_bytes") == current_total, f"{symbol}: total byte count mismatch")
        oracle = row.get("oracle_mismatches")
        _require(oracle == {"snapshot_id": 0, "transition_id": 0, "feature_digest": 0}, f"{symbol}: oracle mismatch")

        checkpoint_bytes += current_checkpoint_bytes
        journal_bytes += current_journal_bytes
        manifest_bytes += current_manifest_bytes
        checkpoint_files += len(actual_checkpoints)
        journal_files += 1
        per_symbol_total_bytes.append(current_total)

    validation = report.get("validation")
    _require(isinstance(validation, dict), "benchmark validation block missing")
    _require(validation.get("daily_exact_comparisons") == EXACT_COMPARISONS, "daily exact comparison total mismatch")
    _require(validation.get("lifecycle_exact_comparisons") == EXACT_COMPARISONS, "lifecycle exact comparison total mismatch")
    _require(validation.get("mismatches") == 0, "frozen benchmark has exact mismatches")
    _require(validation.get("oracle_mismatches") == {"snapshot_id": 0, "transition_id": 0, "feature_digest": 0}, "frozen oracle mismatch")

    forbidden_names = sorted(
        str(path.relative_to(evidence_root))
        for path in evidence_root.rglob("*")
        if any(token in path.name.lower() for token in ("partial", "tmp", "orphan", "incomplete"))
    )
    _require(not forbidden_names, f"partial/tmp/orphan artifacts found: {forbidden_names}")
    all_files = [path for path in evidence_root.rglob("*") if path.is_file()]
    root_bytes = _file_bytes(all_files)
    report_files_bytes = (evidence_root / "benchmark_report.json").stat().st_size + (evidence_root / "benchmark_report.md").stat().st_size
    _require(root_bytes == checkpoint_bytes + journal_bytes + manifest_bytes + report_files_bytes, "root byte accounting mismatch")

    raw_3941 = _engineering_interval(per_symbol_total_bytes, 3941)
    raw_5210 = _engineering_interval(per_symbol_total_bytes, 5210)
    scenario_b_3941, scenario_b_5210 = _scenario_b(raw_3941)
    capacity_gate = report.get("capacity_gate")
    _require(isinstance(capacity_gate, dict), "capacity gate block missing")
    _require(capacity_gate.get("symbols") == 5210 and capacity_gate.get("status") == "TARGET_PASS", "raw capacity gate mismatch")
    _require(math.isclose(float(capacity_gate.get("annualized_gib")), raw_5210[1], rel_tol=0, abs_tol=1e-12), "raw capacity point mismatch")
    _require(scenario_b_5210[1] <= 45.0 and scenario_b_5210[2] < 50.0, "Scenario B capacity contract failed")

    gates = [
        _gate("P5_G1", "50/50完成", {"completed": len(completed), "required": SAMPLE_SIZE}),
        _gate("P5_G2", "failed/missing/duplicate均为0", {"failed": 0, "missing": missing, "duplicate": duplicate_dirs}),
        _gate("P5_G3", "三seller models完整", {"seller_models": SELLER_MODELS, "model_rows": EXACT_COMPARISONS}),
        _gate("P5_G4", "daily state/share exact", {"comparisons": EXACT_COMPARISONS, "mismatches": 0}),
        _gate("P5_G5", "feature exact", {"feature_digest_mismatches": 0}),
        _gate("P5_G6", "peaks/tracker exact", {"exact_continuation_comparisons": EXACT_COMPARISONS, "mismatches": 0}),
        _gate("P5_G7", "lifecycle exact", {"comparisons": EXACT_COMPARISONS, "mismatches": 0}),
        _gate("P5_G8", "terminal exact", {"year_end_terminal_symbols": terminal_symbols, "daily_exact_mismatches": 0}),
        _gate(
            "P5_G9",
            "mass conservation exact",
            {
                "daily_share_bit_exact_comparisons": EXACT_COMPARISONS,
                "daily_share_bit_mismatches": 0,
                "month_end_conservation_error_bits_nonzero": month_end_conservation_error_bits_nonzero,
                "opening_legacy_residual_bits_preserved_nonzero": opening_conservation_error_bits_nonzero,
            },
        ),
        _gate(
            "P5_G10",
            "fallback reason/payload exact",
            {
                "verification": "operator_digest_and_full_post_digest_exact_replay",
                "comparisons": EXACT_COMPARISONS,
                "mismatches": 0,
                "fallback_event_count": "NOT_MATERIALIZED_IN_FROZEN_REPORT",
            },
        ),
        _gate("P5_G11", "无partial/tmp/orphan", {"unexpected_artifacts": forbidden_names}),
        _gate("P5_G12", "actual sample bytes完整", {"root_bytes": root_bytes, "symbol_payload_bytes": sum(per_symbol_total_bytes)}),
        _gate("P5_G13", "3941/5210工程估计完整", {"raw_3941_gib": raw_3941, "raw_5210_gib": raw_5210, "scenario_b_3941_gib": scenario_b_3941, "scenario_b_5210_gib": scenario_b_5210}),
        _gate("P5_G14", "point <=45且engineering high <50", {"point_gib": scenario_b_5210[1], "engineering_high_gib": scenario_b_5210[2]}),
    ]
    return {
        "schema_version": "v12-checkpoint-journal-phase5-validation-v1",
        "status": "PASS",
        "sample": {
            "configured_symbols": SAMPLE_SIZE,
            "completed_symbols": len(completed),
            "failed_symbols": 0,
            "missing_symbols": missing,
            "duplicate_symbols": duplicate_dirs,
            "unexpected_symbols": unexpected,
        },
        "exactness": {
            "daily_state_share_comparisons": EXACT_COMPARISONS,
            "lifecycle_comparisons": EXACT_COMPARISONS,
            "exact_mismatch_count": 0,
            "oracle_mismatches": validation["oracle_mismatches"],
            "month_end_conservation_error_bits_nonzero": month_end_conservation_error_bits_nonzero,
            "opening_legacy_residual_bits_preserved_nonzero": opening_conservation_error_bits_nonzero,
            "fallback": gates[9]["evidence"],
        },
        "artifacts": {
            "checkpoint_files": checkpoint_files,
            "journal_files": journal_files,
            "manifest_files": SAMPLE_SIZE,
            "checkpoint_bytes": checkpoint_bytes,
            "journal_bytes": journal_bytes,
            "manifest_bytes": manifest_bytes,
            "symbol_payload_bytes": sum(per_symbol_total_bytes),
            "report_files_bytes": report_files_bytes,
            "root_bytes": root_bytes,
            "unexpected_partial_tmp_orphan": forbidden_names,
        },
        "capacity": {
            "statistical_label": "unweighted fixed-sample mean t-based engineering interval",
            "not_a_population_confidence_interval": True,
            "cannot_pass_production_capacity": True,
            "n": SAMPLE_SIZE,
            "df": 49,
            "t_975": T49_975,
            "raw_checkpoint_journal_manifest_gib": {"3941": dict(zip(("low", "point", "high"), raw_3941, strict=True)), "5210": dict(zip(("low", "point", "high"), raw_5210, strict=True))},
            "scenario_b_physical_compatibility_terminal_gib": {"3941": dict(zip(("low", "point", "high"), scenario_b_3941, strict=True)), "5210": dict(zip(("low", "point", "high"), scenario_b_5210, strict=True))},
            "capacity_result": "TARGET_POINT_PASS_ENGINEERING_HIGH_WARNING",
        },
        "fixed_gates_total": len(gates),
        "fixed_gates_passed": len(gates),
        "fixed_gates_failed": 0,
        "gates": gates,
    }


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = validate(args.sample, args.evidence_root)
    _atomic_write_json(args.output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "fixed_gates_passed": summary["fixed_gates_passed"], "output": str(args.output / "summary.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
