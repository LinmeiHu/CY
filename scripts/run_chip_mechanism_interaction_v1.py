#!/usr/bin/env python3
"""Evaluate the preregistered training-only chip absorption interaction grid."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from cyq_game.strategy.economic_selection import intracluster_correlation
from cyq_game.strategy.ledger import LedgerEntry, TrialLedger

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/chip_mechanism_interaction_v1.json"
PROTOCOL_MANIFEST = ROOT / "output/chip_mechanism_interaction_v1/protocol_manifest.json"
OUTPUT = ROOT / "output/chip_mechanism_interaction_v1/training_v1"
LEDGER = ROOT / "output/chip_incremental_validation_v1/trials/events.jsonl"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_idempotent(
    event_type: str, payload: dict[str, Any]
) -> LedgerEntry:
    ledger = TrialLedger(LEDGER)
    matches = [
        entry
        for entry in ledger.read_verified()
        if entry.event_type == event_type
        and entry.payload.get("event_id") == payload["event_id"]
    ]
    if matches:
        if len(matches) != 1 or dict(matches[0].payload) != payload:
            raise ValueError(f"conflicting {event_type} ledger event")
        return matches[0]
    return ledger.append(event_type, payload)


def _week(value: Any) -> str:
    day = value if isinstance(value, date) else date.fromisoformat(str(value))
    monday = day.toordinal() - day.weekday()
    return date.fromordinal(monday).isoformat()


def _weekly_values(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    result: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        result[_week(row["trade_date"])].append(float(row["return_fraction"]))
    return dict(result)


def _cluster_evidence(
    rows: list[dict[str, Any]], *, seed: int, resamples: int
) -> tuple[dict[str, Any], np.ndarray]:
    clusters = _weekly_values(rows)
    flat = [value for values in clusters.values() for value in values]
    if not flat or len(clusters) < 2:
        return (
            {
                "trades": len(flat),
                "weeks": len(clusters),
                "observed_icc": None,
                "effective_sample": 0.0,
                "mean_return": None,
                "bootstrap_lower_95": None,
                "bootstrap_upper_95": None,
                "bootstrap_p_one_sided": 1.0,
            },
            np.full(resamples, np.nan),
        )
    groups = tuple(tuple(values) for _, values in sorted(clusters.items()))
    icc = intracluster_correlation(groups)
    mean_size = len(flat) / len(groups)
    effective = len(flat) / (1 + (mean_size - 1) * max(icc, 0.10))
    weekly_means = np.asarray([fmean(values) for values in groups], dtype=np.float64)
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(weekly_means), size=(resamples, len(weekly_means)))
    bootstrap = weekly_means[indexes].mean(axis=1)
    return (
        {
            "trades": len(flat),
            "weeks": len(groups),
            "observed_icc": icc,
            "effective_sample": effective,
            "mean_return": fmean(flat),
            "equal_week_mean_return": float(weekly_means.mean()),
            "bootstrap_lower_95": float(np.quantile(bootstrap, 0.025)),
            "bootstrap_upper_95": float(np.quantile(bootstrap, 0.975)),
            "bootstrap_p_one_sided": float(
                (1 + np.count_nonzero(bootstrap <= 0)) / (resamples + 1)
            ),
        },
        bootstrap,
    )


def _difference_evidence(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    left_week = {key: fmean(values) for key, values in _weekly_values(left).items()}
    right_week = {key: fmean(values) for key, values in _weekly_values(right).items()}
    common = sorted(set(left_week) & set(right_week))
    if len(common) < 2:
        return {
            "common_weeks": len(common),
            "mean_weekly_difference": None,
            "bootstrap_lower_95": None,
            "bootstrap_upper_95": None,
        }
    differences = np.asarray(
        [left_week[key] - right_week[key] for key in common], dtype=np.float64
    )
    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(differences), size=(resamples, len(differences)))
    bootstrap = differences[indexes].mean(axis=1)
    return {
        "common_weeks": len(common),
        "mean_weekly_difference": float(differences.mean()),
        "bootstrap_lower_95": float(np.quantile(bootstrap, 0.025)),
        "bootstrap_upper_95": float(np.quantile(bootstrap, 0.975)),
    }


def _maximum_drawdown(rows: list[dict[str, Any]]) -> float:
    weekly = _weekly_values(rows)
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for key in sorted(weekly):
        cumulative += fmean(weekly[key])
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return drawdown


def _blocked_exit_cvar95(rows: list[dict[str, Any]]) -> float:
    losses = sorted(
        max(float(row.get("outcome_blocked_tail_loss") or 0.0), 0.0)
        for row in rows
    )
    if not losses:
        return 0.0
    count = max(1, math.ceil(len(losses) * 0.05))
    return fmean(losses[-count:])


def _parameter_id(migration: float, disagreement: float, overhead: float) -> str:
    raw = f"{migration:.6f}|{disagreement:.6f}|{overhead:.6f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _finite_or_negative_infinity(value: Any) -> float:
    """Keep a legitimate zero bound while failing closed on missing evidence."""
    return -math.inf if value is None else float(value)


def _holm_passes(metrics: list[dict[str, Any]], alpha: float = 0.05) -> None:
    ordered = sorted(
        metrics,
        key=lambda item: float(item["absolute"]["bootstrap_p_one_sided"]),
    )
    rejection_open = True
    total = len(ordered)
    for rank, item in enumerate(ordered, start=1):
        threshold = alpha / (total - rank + 1)
        p_value = float(item["absolute"]["bootstrap_p_one_sided"])
        passed = rejection_open and p_value <= threshold
        item["holm"] = {
            "rank": rank,
            "threshold": threshold,
            "p_value": p_value,
            "pass": passed,
        }
        if not passed:
            rejection_open = False


def _adjacent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    coordinates = ("migration_index", "disagreement_index", "overhead_index")
    distances = [abs(int(left[key]) - int(right[key])) for key in coordinates]
    return sum(value != 0 for value in distances) == 1 and sum(distances) == 1


def _components(metrics: list[dict[str, Any]]) -> list[list[str]]:
    passing = [item for item in metrics if item["base_gate_pass"]]
    by_id = {str(item["parameter_id"]): item for item in passing}
    graph = {
        key: {
            other
            for other, candidate in by_id.items()
            if other != key and _adjacent(item, candidate)
        }
        for key, item in by_id.items()
    }
    result: list[list[str]] = []
    remaining = set(graph)
    while remaining:
        start = min(remaining)
        queue = deque([start])
        component: list[str] = []
        remaining.remove(start)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(graph[current] & remaining):
                remaining.remove(neighbor)
                queue.append(neighbor)
        result.append(sorted(component))
    return sorted(result, key=lambda item: (-len(item), item))


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL_MANIFEST.read_text(encoding="utf-8"))
    if protocol.get("status") != "PREREGISTERED":
        raise ValueError("protocol is not preregistered")
    if protocol.get("config_sha256") != _sha256(CONFIG):
        raise ValueError("protocol config hash changed after preregistration")
    data_path = ROOT / config["data_contract"]["development_input"]
    if _sha256(data_path) != config["data_contract"]["development_input_sha256"]:
        raise ValueError("development input hash changed")
    run_id = str(protocol["ledger"]["run_id"])
    started_payload = {
        "event_id": hashlib.sha256(f"{run_id}|TRAINING_STARTED".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_id": config["protocol_id"],
        "parameter_count": 27,
        "development_classification": "PREVIOUSLY_OBSERVED_TRAINING_ONLY",
        "maximum_selection_year": 2022,
        "2023_or_later_accessed": False,
    }
    started = _append_idempotent("CHIP_MECHANISM_INTERACTION_TRAINING_STARTED", started_payload)
    rows = [
        dict(row)
        for row in pq.read_table(data_path).to_pylist()
        if row["module"] == config["data_contract"]["allowed_module"]
    ]
    if not rows or max(row["trade_date"].year for row in rows) != 2022:
        raise ValueError("unexpected development date coverage")
    base_rows = [
        row
        for row in rows
        if row["chip_measurement_valid"]
        and row["research_hard_valid"]
        and float(row["market_return_20"]) > 0
        and float(row["sector_return_20"]) > 0
    ]
    baseline_closed = [row for row in base_rows if row.get("return_fraction") is not None]
    baseline_drawdown = _maximum_drawdown(baseline_closed)
    baseline_cvar = _blocked_exit_cvar95(baseline_closed)
    grids = config["mechanism_parameters"]
    parameters: list[dict[str, Any]] = []
    for migration_index, migration in enumerate(grids["cost_migration_floor_vol"]):
        for disagreement_index, disagreement in enumerate(
            grids["seller_model_disagreement_cap_atr"]
        ):
            for overhead_index, overhead in enumerate(
                grids["overhead_distance_cap_atr"]
            ):
                parameter_id = _parameter_id(migration, disagreement, overhead)

                def fixed(
                    row: dict[str, Any],
                    *,
                    overhead_bound: float = float(overhead),
                    disagreement_bound: float = float(disagreement),
                ) -> bool:
                    atr = float(row["atr14"])
                    return (
                        atr > 0
                        and float(row["close"]) >= float(row["exact_p50"])
                        and float(row["profit_ratio_change_20"]) >= 0
                        and float(row["i90_contraction_20"]) >= 0
                        and (float(row["close"]) - float(row["i90_upper"])) / atr <= 0.25
                        and (float(row["i90_upper"]) - float(row["close"])) / atr
                        <= overhead_bound
                        and float(row["seller_model_disagreement_atr"])
                        <= disagreement_bound
                    )

                current_all = [
                    row
                    for row in base_rows
                    if fixed(row)
                    and float(row["price_minus_cost_migration_20_vol"])
                    >= float(migration)
                ]
                stale_all = [
                    row
                    for row in base_rows
                    if fixed(row)
                    and float(row["stale_price_minus_cost_migration_20_vol"])
                    >= float(migration)
                ]
                current = [
                    row for row in current_all if row.get("return_fraction") is not None
                ]
                stale = [row for row in stale_all if row.get("return_fraction") is not None]
                seed = int.from_bytes(
                    hashlib.sha256(f"{run_id}|{parameter_id}".encode()).digest()[:8],
                    "big",
                )
                absolute, _ = _cluster_evidence(
                    current,
                    seed=seed,
                    resamples=int(config["evaluation"]["bootstrap_replicates"]),
                )
                baseline_difference = _difference_evidence(
                    current,
                    baseline_closed,
                    seed=seed ^ 0xBACE,
                    resamples=int(config["evaluation"]["bootstrap_replicates"]),
                )
                stale_difference = _difference_evidence(
                    current,
                    stale,
                    seed=seed ^ 0x57A1E,
                    resamples=int(config["evaluation"]["bootstrap_replicates"]),
                )
                fold_means = {
                    fold: fmean(
                        float(row["return_fraction"])
                        for row in current
                        if row["fold_id"] == fold
                    )
                    if any(row["fold_id"] == fold for row in current)
                    else None
                    for fold in (
                        "FIT_2020_EVALUATE_2021",
                        "FIT_2020_2021_EVALUATE_2022",
                    )
                }
                fold_weeks = {
                    fold: len(
                        {
                            _week(row["trade_date"])
                            for row in current
                            if row["fold_id"] == fold
                        }
                    )
                    for fold in fold_means
                }
                fill_rate = sum(row["outcome_status"] == "FILLED" for row in current_all) / max(
                    len(current_all), 1
                )
                closure_rate = len(current) / max(
                    sum(row["outcome_status"] == "FILLED" for row in current_all), 1
                )
                drawdown = _maximum_drawdown(current)
                cvar = _blocked_exit_cvar95(current)
                parameters.append(
                    {
                        "parameter_id": parameter_id,
                        "migration_index": migration_index,
                        "disagreement_index": disagreement_index,
                        "overhead_index": overhead_index,
                        "parameters": {
                            "cost_migration_floor_vol": migration,
                            "seller_model_disagreement_cap_atr": disagreement,
                            "overhead_distance_cap_atr": overhead,
                        },
                        "absolute": absolute,
                        "incremental_vs_price_regime": baseline_difference,
                        "incremental_vs_stale_chip": stale_difference,
                        "fold_means": fold_means,
                        "fold_weeks": fold_weeks,
                        "entry_fill_rate": fill_rate,
                        "closure_rate": closure_rate,
                        "maximum_drawdown": drawdown,
                        "baseline_maximum_drawdown": baseline_drawdown,
                        "blocked_exit_cvar95": cvar,
                        "baseline_blocked_exit_cvar95": baseline_cvar,
                    }
                )
    _holm_passes(parameters)
    thresholds = config["power_and_risk_gates"]
    for item in parameters:
        gates = {
            "effective_sample": float(item["absolute"]["effective_sample"])
            >= float(thresholds["minimum_effective_sample"]),
            "distinct_weeks": int(item["absolute"]["weeks"])
            >= int(thresholds["minimum_distinct_weeks"]),
            "fold_weeks": all(
                int(value) >= int(thresholds["minimum_weeks_per_evaluation_fold"])
                for value in item["fold_weeks"].values()
            ),
            "both_fold_means_positive": all(
                value is not None and float(value) > 0
                for value in item["fold_means"].values()
            ),
            "holm_absolute_return": bool(item["holm"]["pass"])
            and _finite_or_negative_infinity(
                item["absolute"]["bootstrap_lower_95"]
            )
            > 0,
            "incremental_price_regime": _finite_or_negative_infinity(
                item["incremental_vs_price_regime"]["bootstrap_lower_95"]
            )
            >= float(thresholds["incremental_over_fixed_price_volume_regime_lower_bound_min"]),
            "incremental_stale_chip": _finite_or_negative_infinity(
                item["incremental_vs_stale_chip"]["bootstrap_lower_95"]
            )
            > 0,
            "entry_fill_rate": float(item["entry_fill_rate"])
            >= float(thresholds["entry_fill_rate_min"]),
            "closure_rate": float(item["closure_rate"])
            >= float(thresholds["closure_rate_min"]),
            "drawdown": float(item["maximum_drawdown"])
            >= float(item["baseline_maximum_drawdown"]),
            "blocked_exit_cvar95": float(item["blocked_exit_cvar95"])
            <= float(item["baseline_blocked_exit_cvar95"]),
        }
        item["gates"] = gates
        item["base_gate_pass"] = all(gates.values())
    components = _components(parameters)
    eligible_components = [
        component
        for component in components
        if len(component)
        >= int(config["robust_selection"]["minimum_connected_component_nodes"])
    ]
    by_id = {str(item["parameter_id"]): item for item in parameters}
    selected_component = eligible_components[0] if eligible_components else []
    selected_parameter_id = None
    if selected_component:
        selected_parameter_id = max(
            selected_component,
            key=lambda key: (
                min(float(value) for value in by_id[key]["fold_means"].values()),
                -float(by_id[key]["parameters"]["seller_model_disagreement_cap_atr"]),
                -float(by_id[key]["parameters"]["overhead_distance_cap_atr"]),
                key,
            ),
        )
    decision = (
        "TRAINING_CANDIDATE_PROSPECTIVE_ONLY" if selected_parameter_id else "NO_TRADE"
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    metrics_path = OUTPUT / "parameter_metrics.json"
    decision_path = OUTPUT / "robust_region_decision.json"
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "classification": "PREVIOUSLY_OBSERVED_TRAINING_ONLY",
                "parameters": parameters,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    decision_payload = {
        "decision": decision,
        "passing_parameter_ids": [
            str(item["parameter_id"]) for item in parameters if item["base_gate_pass"]
        ],
        "components": components,
        "eligible_components": eligible_components,
        "selected_component": selected_component,
        "selected_parameter_id": selected_parameter_id,
        "promotion_authorized": False,
        "prospective_shadow_start": "2026-08-25",
        "prospective_shadow_minimum_weeks": 52,
    }
    decision_path.write_text(
        json.dumps(decision_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_id": run_id,
        "protocol_id": config["protocol_id"],
        "protocol_manifest": str(PROTOCOL_MANIFEST),
        "protocol_manifest_sha256": _sha256(PROTOCOL_MANIFEST),
        "started_ledger_sequence": started.sequence,
        "classification": "PREVIOUSLY_OBSERVED_TRAINING_ONLY",
        "maximum_selection_year": 2022,
        "2023_or_later_accessed": False,
        "parameter_count": len(parameters),
        "passing_parameter_count": len(decision_payload["passing_parameter_ids"]),
        "decision": decision,
        "selected_parameter_id": selected_parameter_id,
        "promotion_authorized": False,
        "inventory": [
            {"path": metrics_path.name, "sha256": _sha256(metrics_path)},
            {"path": decision_path.name, "sha256": _sha256(decision_path)},
        ],
        "runner_sha256": _sha256(Path(__file__)),
    }
    manifest_path = OUTPUT / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    complete_payload = {
        "event_id": hashlib.sha256(f"{run_id}|TRAINING_COMPLETE".encode()).hexdigest(),
        "run_id": run_id,
        "protocol_id": config["protocol_id"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256(manifest_path),
        "parameter_count": len(parameters),
        "passing_parameter_count": len(decision_payload["passing_parameter_ids"]),
        "decision": decision,
        "selected_parameter_id": selected_parameter_id,
        "development_classification": "PREVIOUSLY_OBSERVED_TRAINING_ONLY",
        "maximum_selection_year": 2022,
        "2023_or_later_accessed": False,
        "promotion_authorized": False,
    }
    _append_idempotent("CHIP_MECHANISM_INTERACTION_TRAINING_COMPLETE", complete_payload)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
