#!/usr/bin/env python3
"""Invalidate the frequency shortlist and preregister economic entry selection v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyq_game.strategy.ledger import LedgerEntry, TrialLedger
from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage

PROTOCOL_VERSION = "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2"
INVALIDATION_REASON = "ENTRY_FREQUENCY_GATE_HAS_NO_ECONOMIC_OR_ADJACENCY_VALIDITY"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    entry_path = _entry_frequency_path(config)
    entry = _read_object(entry_path)
    _validate_frequency_artifact(entry, config)
    exact_manifests = _exact_diagnostic_manifests(config)
    _assert_holdout_locked(config)
    source_inventory = _source_inventory(entry_path, exact_manifests)
    invalidation = _invalidation_payload(config, entry, source_inventory)
    ledger = TrialLedger(config.trial_ledger)
    invalidation_entry = _append_idempotent(
        ledger, "ENTRY_SELECTION_PROTOCOL_INVALIDATED", invalidation
    )
    protocol = _economic_protocol_payload(config, entry)
    protocol_entry = _append_idempotent(
        ledger, "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2", protocol
    )
    review = {
        "schema_version": 2,
        "status": "ACTION_REQUIRED",
        "generated_at": invalidation_entry.recorded_at,
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "old_entry_selection": {
            "status": "DIAGNOSTIC_ONLY",
            "formal_selection_eligible": False,
            "reason": INVALIDATION_REASON,
            "entry_lattice_snapshot_id": entry["entry_lattice_snapshot_id"],
            "candidate_parameter_ids": entry["candidate_parameter_ids"],
            "candidate_adjacent_frequency_passes": [0, 0],
            "parameter_trials": 81,
        },
        "old_exact_exit_outputs": {
            "status": "DIAGNOSTIC_ONLY",
            "formal_selection_eligible": False,
            "manifests": source_inventory["exact_exit_manifests"],
        },
        "source_inventory": source_inventory,
        "ledger_events": {
            "invalidation": {
                "event_id": invalidation["event_id"],
                "sequence": invalidation_entry.sequence,
                "entry_hash": invalidation_entry.entry_hash,
            },
            "economic_protocol_v2": {
                "event_id": protocol["event_id"],
                "run_id": protocol["run_id"],
                "sequence": protocol_entry.sequence,
                "entry_hash": protocol_entry.entry_hash,
            },
        },
        "holdout_lock": {
            "year": 2023,
            "accessed": False,
            "freeze_manifest_exists": config.freeze_manifest.exists(),
            "resealed_artifact_paths_exist": False,
            "ledger_holdout_accessed_true_events": 0,
            "unlock_requires": [
                "ENTRY_ECONOMIC_SELECTION_PROTOCOL_V2_COMPLETE",
                "PIT_B_TRUE_OOS_CALIBRATION_GATE_COMPLETE",
                "STRATEGY_FREEZE_PASS_OR_NO_TRADE",
            ],
        },
        "next_required_action": "PIT_B_P0_TRUE_OOS_CORRECTION_THEN_81_GRID_ECONOMIC_EVALUATION",
    }
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_selection_protocol_review_v2.json"
    )
    _write_immutable_json(target, review)
    print(json.dumps(review, ensure_ascii=False, indent=2))
    return 0


def _entry_frequency_path(config: MarkupRetestConfig) -> Path:
    return (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_frequency.json"
    )


def _validate_frequency_artifact(
    payload: Mapping[str, Any], config: MarkupRetestConfig
) -> None:
    if payload.get("status") != "PASS":
        raise ValueError("the frequency artifact is not the superseded PASS artifact")
    if payload.get("config_sha256") != config.sha256:
        raise ValueError("frequency artifact config hash mismatch")
    trials = payload.get("trials")
    candidates = payload.get("candidate_parameter_ids")
    if not isinstance(trials, list) or len(trials) != 81:
        raise ValueError("frequency artifact must contain all 81 diagnostic trials")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("frequency artifact must contain the two superseded candidates")
    by_id = {str(row["parameter_id"]): row for row in trials}
    adjacent = [int(by_id[str(item)]["adjacent_frequency_passes"]) for item in candidates]
    if adjacent != [0, 0]:
        raise ValueError("superseded candidates no longer match the reviewed evidence")


def _exact_diagnostic_manifests(config: MarkupRetestConfig) -> tuple[Path, ...]:
    root = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
    )
    manifests = tuple(sorted(root.glob("exact_exit_lattice-*/manifest.json")))
    if len(manifests) < 2:
        raise ValueError("expected the preserved original and coordinate-v2 exact manifests")
    for path in manifests:
        payload = _read_object(path)
        if payload.get("config_sha256") != config.sha256:
            raise ValueError(f"exact diagnostic config hash mismatch: {path}")
        if payload.get("holdout_accessed") is not False:
            raise ValueError(f"exact diagnostic is holdout-tainted: {path}")
    return manifests


def _assert_holdout_locked(config: MarkupRetestConfig) -> None:
    if config.freeze_manifest.exists():
        raise ValueError("frequency invalidation must precede every strategy freeze")
    for name in ("panel", "signals", "labels", "validation"):
        if (config.outputs.root / name / StrategyStage.RESEALED.value).exists():
            raise ValueError(f"2023 resealed artifact already exists under {name}")
    for entry in TrialLedger(config.trial_ledger).read_verified():
        if entry.payload.get("holdout_accessed") is True:
            raise ValueError(
                f"ledger already records holdout access at sequence {entry.sequence}"
            )


def _source_inventory(
    entry_path: Path, exact_manifests: Sequence[Path]
) -> dict[str, Any]:
    return {
        "entry_frequency": _file_record(entry_path),
        "exact_exit_manifests": [
            {
                **_file_record(path),
                "exact_exit_lattice_snapshot_id": _read_object(path).get(
                    "exact_exit_lattice_snapshot_id"
                ),
            }
            for path in exact_manifests
        ],
        "code": [
            _file_record(Path("src/cyq_game/strategy/research.py")),
            _file_record(Path("src/cyq_game/strategy/exact_replay.py")),
            _file_record(Path("scripts/run_markup_retest_entry_lattice.py")),
            _file_record(Path("scripts/run_markup_retest_exact_exit_lattice.py")),
        ],
        "git_head": _git_head(),
    }


def _invalidation_payload(
    config: MarkupRetestConfig,
    entry: Mapping[str, Any],
    source_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    identity = (
        f"ENTRY_SELECTION_PROTOCOL_INVALIDATED|{config.sha256}|"
        f"{entry['entry_lattice_snapshot_id']}|{INVALIDATION_REASON}"
    )
    return {
        "event_id": hashlib.sha256(identity.encode()).hexdigest(),
        "config_sha256": config.sha256,
        "entry_lattice_snapshot_id": entry["entry_lattice_snapshot_id"],
        "candidate_parameter_ids": entry["candidate_parameter_ids"],
        "candidate_adjacent_frequency_passes": [0, 0],
        "parameter_trials_without_economic_evaluation": 79,
        "old_entry_status": "DIAGNOSTIC_ONLY",
        "old_exact_exit_status": "DIAGNOSTIC_ONLY",
        "formal_selection_eligible": False,
        "reason_codes": [
            INVALIDATION_REASON,
            "ADJACENT_FREQUENCY_PASSES_ZERO_WAS_NOT_A_HARD_GATE",
            "FREQUENCY_THRESHOLDS_HAVE_NO_POWER_CAPACITY_OR_ECONOMIC_BASIS",
            "SEVENTY_NINE_ENTRY_POINTS_HAVE_NO_COMPARABLE_EXACT_ECONOMIC_EVIDENCE",
        ],
        "source_inventory": source_inventory,
        "holdout_accessed": False,
    }


def _economic_protocol_payload(
    config: MarkupRetestConfig, entry: Mapping[str, Any]
) -> dict[str, Any]:
    parameter_ids = tuple(str(row["parameter_id"]) for row in entry["trials"])
    run_id = hashlib.sha256(
        (
            f"{PROTOCOL_VERSION}|{config.sha256}|"
            f"{entry['panel_snapshot_id']}|{'|'.join(parameter_ids)}"
        ).encode()
    ).hexdigest()
    # One-sided alpha=.05, power=.80, reference sigma=8%, minimum meaningful
    # net effect=1%: ceil(((1.644854+0.841621)*.08/.01)^2) = 396.
    iid_power_required = 396
    return {
        "event_id": hashlib.sha256(f"{run_id}|PROTOCOL".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_version": PROTOCOL_VERSION,
        "config_sha256": config.sha256,
        "panel_snapshot_id": entry["panel_snapshot_id"],
        "superseded_entry_lattice_snapshot_id": entry["entry_lattice_snapshot_id"],
        "development_period": {
            "start": "2020-01-02",
            "end": "2022-12-30",
            "classification": "WALK_FORWARD_DEVELOPMENT_EVIDENCE",
            "never_describe_as_untouched_oos": True,
        },
        "parameter_grid": {
            "count": 81,
            "parameter_ids": list(parameter_ids),
            "parameters": [row["parameters"] for row in entry["trials"]],
            "entry_dimensions": [
                "setup_score_min",
                "breakout_buffer_atr",
                "max_retest_depth_atr",
                "min_cost_migration_atr",
            ],
            "controlled_exit_parameters": {
                "distribution_score_min": 0.8,
                "protective_stop_atr": 1.5,
            },
            "all_points_require_same_exact_economic_evaluation": True,
        },
        "frequency_policy": {
            "annual_signal_100_to_200_is_gate": False,
            "three_year_mean_120_to_180_is_gate": False,
            "annual_counts_are_diagnostics_only": True,
            "high_signal_count_rejects_only_for_capacity_exposure_impact_or_tail_failure": True,
        },
        "sample_sufficiency": {
            "minimum_meaningful_net_return_fraction": 0.01,
            "reference_trade_return_standard_deviation": 0.08,
            "one_sided_alpha": 0.05,
            "power": 0.80,
            "iid_effective_sample_required": iid_power_required,
            "correlation_cluster": "SIGNAL_ISO_WEEK",
            "intracluster_correlation_floor": 0.10,
            "effective_sample_formula": "n/(1+(mean_cluster_size-1)*max(observed_icc,0.10))",
            "minimum_distinct_signal_weeks": 104,
            "bootstrap": {
                "unit": "SIGNAL_ISO_WEEK",
                "resamples": 10000,
                "seed": "sha256(parameter_id|ENTRY_ECONOMIC_SELECTION_V2)[:16]",
                "confidence": 0.95,
                "maximum_two_sided_ci_half_width": 0.01,
            },
            "failure_status": "INSUFFICIENT_EVIDENCE",
        },
        "exact_execution": {
            "signal_fill": "NEXT_LEGAL_5M_WINDOW_ONLY",
            "same_bar_fill_forbidden": True,
            "fees_bps": config.execution.fee_bps,
            "slippage_bps": config.execution.slippage_bps,
            "impact_bps": config.execution.impact_bps,
            "blocked_exits_persist": True,
            "corporate_action_unknown_blocks_new_risk": True,
            "minimum_entry_fill_rate": 0.95,
            "minimum_closed_trade_rate": 0.95,
        },
        "economic_gates": {
            "primary_estimator": "TRIMMED_5PCT_MEAN_NET_RETURN_FRACTION",
            "weekly_block_bootstrap_lower_95_strictly_positive": True,
            "matched_eligible_baseline_difference_lower_95_strictly_positive": True,
            "no_trade_baseline_return_fraction": 0.0,
            "profit_factor_minimum": 1.0,
            "calendar_year_results_are_diagnostics_not_hard_gates": True,
        },
        "risk_gates": {
            "research_book_capital": 25000000.0,
            "nominal_capital_per_signal": config.execution.nominal_capital_per_signal,
            "portfolio_max_drawdown_fraction": 0.20,
            "blocked_tail_loss_over_entry_cash_max": 0.01,
            "one_percent_trade_cvar_floor": -0.25,
            "event_sequence_drawdown_is_reported": True,
        },
        "capacity_gates": {
            "maximum_concurrent_positions": 50,
            "maximum_concurrent_same_industry_positions": 10,
            "first_5m_participation_p95_max": 0.10,
            "first_5m_participation_absolute_max": 0.25,
            "maximum_same_day_new_entries": 10,
            "signal_count_alone_is_not_a_failure": True,
        },
        "matched_eligible_baseline": {
            "sampling": "DETERMINISTIC_HASH_WITHIN_YEAR_BOARD_MARKET_SECTOR_STRATA",
            "entry": "NEXT_LEGAL_5M_WINDOW_WITH_IDENTICAL_COSTS",
            "exit": "TWENTIETH_LEGAL_SESSION_5M_WINDOW_WITH_IDENTICAL_COSTS",
            "candidate_attribution_exit": "SAME_FIXED_TWENTY_SESSION_EXIT",
            "lookahead_fields_forbidden": True,
        },
        "economic_neighborhood": {
            "adjacency": "ONE_OF_FOUR_ENTRY_DIMENSIONS_MOVES_EXACTLY_ONE_GRID_STEP",
            "adjacent_economic_passes_minimum": 1,
            "connected_passing_component_size_minimum": 3,
            "isolated_best_point_selectable": False,
            "setup_score_refinement_step_if_needed": 0.2,
            "pseudo_steps_0.7_or_0.9_forbidden": True,
            "refinement_requires_new_protocol_and_incremental_parameter_hash_cache": True,
        },
        "selection_rule": {
            "select_component_before_parameter": True,
            "component_sort": [
                "descending_minimum_node_bootstrap_lower_bound",
                "ascending_worst_node_portfolio_drawdown",
                "ascending_worst_node_blocked_tail_loss_ratio",
                "lexicographic_component_parameter_ids",
            ],
            "parameter_within_component": "MANHATTAN_GRID_MEDOID_THEN_PARAMETER_ID",
            "exit_grid_tuning_before_robust_entry_component": False,
        },
        "allowed_terminal_decisions": ["PASS", "NO_TRADE"],
        "no_trade_reasons": [
            "INSUFFICIENT_EVIDENCE",
            "NO_ROBUST_ENTRY_REGION",
            "ECONOMIC_GATE_FAILED",
            "RISK_GATE_FAILED",
            "CAPACITY_GATE_FAILED",
            "PIT_B_TRUE_OOS_CALIBRATION_GATE_FAILED",
        ],
        "holdout_lock": {
            "year": 2023,
            "accessed": False,
            "read_before_protocol_complete": "FAIL_CLOSED",
            "read_before_pit_b_p0_gate_complete": "FAIL_CLOSED",
            "final_access_count": 1,
            "retuning_after_access": False,
        },
        "holdout_accessed": False,
    }


def _append_idempotent(
    ledger: TrialLedger, event_type: str, payload: Mapping[str, Any]
) -> LedgerEntry:
    event_id = str(payload["event_id"])
    for entry in ledger.read_verified():
        if entry.payload.get("event_id") != event_id:
            continue
        if entry.event_type != event_type or entry.payload != payload:
            raise ValueError(f"trial ledger event collision: {event_id}")
        return entry
    return ledger.append(event_type, payload)


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"immutable review artifact differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
