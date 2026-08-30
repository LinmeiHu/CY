#!/usr/bin/env python3
"""Construct frozen MKT-MIN-PATH-001 non-slope five-day trajectories."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPTS = PROGRAM / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_mkt_shock_001 import _spearman  # noqa: E402
from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-MIN-PATH-002_spec.json"
DAILY_PATH = PROGRAM / "artifacts/MKT-MIN-001_daily_market_panel.csv"
SOURCE_TRAJECTORY_PATH = PROGRAM / "artifacts/MKT-MIN-001_trajectory_panel.parquet"
SOURCE_RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-001_result.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-PATH-002_nonslope_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-PATH-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-PATH-002_nonslope_trajectory.md"
EXPECTED_SPEC_SHA256 = "161b4bb79795e525940eb6d69d581db22ec1500a025b39b6bd586066ac6bf70c"
KEYS = ["trade_date", "market_view", "denominator"]
OPERATORS = ("ordinal_progression", "signed_reversal", "curvature")


class NonSlopeTrajectoryError(RuntimeError):
    """Fail-closed MKT-MIN-PATH-001 construction error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise NonSlopeTrajectoryError("frozen spec identity changed")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    parent_path = ROOT / control["inherits_scientific_design_path"]
    if sha256_file(parent_path) != control["inherits_scientific_design_sha256"]:
        raise NonSlopeTrajectoryError("inherited scientific design identity changed")
    spec = json.loads(parent_path.read_text(encoding="utf-8"))
    if control["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise NonSlopeTrajectoryError("scientific spec is not frozen")
    spec["experiment_id"] = control["experiment_id"]
    spec["status"] = control["status"]
    spec["population"]["decision_at"] = control["only_semantic_correction"][
        "trajectory_available_at"
    ]
    spec["outputs"] = control["outputs"]
    spec["inherited_scientific_design_sha256"] = control[
        "inherits_scientific_design_sha256"
    ]
    return spec


def _descriptors(spec: dict[str, Any]) -> list[str]:
    return [name for family in spec["descriptors"].values() for name in family]


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_item = spec["inputs"]["daily_panel"]
    trajectory_item = spec["inputs"]["trajectory_panel"]
    if sha256_file(DAILY_PATH) != daily_item["sha256"]:
        raise NonSlopeTrajectoryError("bound daily panel identity changed")
    if sha256_file(SOURCE_TRAJECTORY_PATH) != trajectory_item["sha256"]:
        raise NonSlopeTrajectoryError("bound trajectory panel identity changed")
    if sha256_file(SOURCE_RESULT_PATH) != spec["inputs"]["source_result_sha256"]:
        raise NonSlopeTrajectoryError("bound source result identity changed")
    descriptors = _descriptors(spec)
    daily_columns = [
        *KEYS, "available_at", "hard_valid", "descriptor_coverage",
        "cy6_snapshot_sha256", "cy8_snapshot_selection_sha256",
        *[f"{name}__{aggregation}" for name in descriptors for aggregation in ("median", "p40", "p60")],
    ]
    trajectory_columns = [
        *KEYS, "available_at", "hard_valid", "descriptor_coverage",
        "cy6_snapshot_sha256", "cy8_snapshot_selection_sha256",
        *[f"{name}__day_m{day}" for name in descriptors for day in (5, 4, 3, 2, 1)],
    ]
    forbidden_tokens = (
        "ols_slope", "endpoint_change", "endpoint_slope", "signed_monotonic_fraction",
        "slope_acceleration", "reversal_shape",
    )
    if any(token in column for column in [*daily_columns, *trajectory_columns] for token in forbidden_tokens):
        raise NonSlopeTrajectoryError("forbidden old shape field entered whitelist")
    daily = pd.read_csv(DAILY_PATH, usecols=daily_columns)
    trajectory = pd.read_parquet(SOURCE_TRAJECTORY_PATH, columns=trajectory_columns)
    for label, frame, expected in (
        ("daily", daily, daily_item["rows"]),
        ("trajectory", trajectory, trajectory_item["rows"]),
    ):
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        if len(frame) != expected or frame.duplicated(KEYS).any():
            raise NonSlopeTrajectoryError(f"{label} population/key changed")
        if not frame.hard_valid.astype(bool).all() or frame.trade_date.max() > pd.Timestamp("2023-12-31"):
            raise NonSlopeTrajectoryError(f"invalid/post-2023 {label} row entered")
        if frame.descriptor_coverage.min() < 0.95:
            raise NonSlopeTrajectoryError(f"{label} descriptor coverage changed")
    if not daily.groupby(["market_view", "denominator"]).size().eq(1457).all():
        raise NonSlopeTrajectoryError("daily group size changed")
    if not trajectory.groupby(["market_view", "denominator"]).size().eq(1453).all():
        raise NonSlopeTrajectoryError("trajectory group size changed")
    available = pd.to_datetime(trajectory.available_at)
    if not (available.dt.hour.eq(15) & available.dt.minute.eq(30)).all():
        raise NonSlopeTrajectoryError("trajectory is not available at frozen 15:30 time")
    return (
        daily.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True),
        trajectory.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True),
    )


def _rank_time_correlation(values: np.ndarray) -> np.ndarray:
    """Rowwise Spearman correlation of five values with time; flat rows emit zero."""
    order = np.argsort(values, axis=1, kind="mergesort")
    sorted_values = np.take_along_axis(values, order, axis=1)
    ranks = np.empty_like(values, dtype=float)
    for row in range(len(values)):
        start = 0
        while start < 5:
            end = start + 1
            while end < 5 and sorted_values[row, end] == sorted_values[row, start]:
                end += 1
            average_rank = (start + 1 + end) / 2.0
            ranks[row, order[row, start:end]] = average_rank
            start = end
    centered = ranks - 3.0
    time = np.arange(5, dtype=float) - 2.0
    denominator = np.sqrt(np.square(centered).sum(axis=1) * np.square(time).sum())
    numerator = centered @ time
    return np.divide(numerator, denominator, out=np.zeros(len(values)), where=denominator > 0)


def nonslope_operators(values: np.ndarray) -> dict[str, np.ndarray]:
    """Apply the three frozen operators and their two definition neighbors."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[1] != 5:
        raise NonSlopeTrajectoryError("operator input must be rows x five days")
    finite = np.isfinite(values).all(axis=1)
    differences = np.diff(values, axis=1)
    adjacent_balance = np.sign(differences).mean(axis=1)
    pair_differences = np.column_stack([
        values[:, later] - values[:, earlier]
        for earlier in range(5) for later in range(earlier + 1, 5)
    ])
    pair_balance = np.sign(pair_differences).mean(axis=1)
    rank_time = _rank_time_correlation(values)

    early = differences[:, :2].mean(axis=1)
    late = differences[:, 2:].mean(axis=1)
    reversal_primary = np.where(np.sign(early) * np.sign(late) == -1, np.sign(late), 0.0)
    reversal_outer = np.where(
        np.sign(differences[:, 0]) * np.sign(differences[:, 3]) == -1,
        np.sign(differences[:, 3]), 0.0,
    )
    early_half = values[:, 2] - values[:, :2].mean(axis=1)
    late_half = values[:, 3:].mean(axis=1) - values[:, 2]
    reversal_halves = np.where(
        np.sign(early_half) * np.sign(late_half) == -1, np.sign(late_half), 0.0
    )

    curvature_primary = late - early
    curvature_outer = differences[:, 3] - differences[:, 0]
    curvature_midpoint = values[:, 4] - 2.0 * values[:, 2] + values[:, 0]
    result = {
        "ordinal_progression": adjacent_balance,
        "ordinal_progression_neighbor_all_pairs": pair_balance,
        "ordinal_progression_neighbor_rank_time": rank_time,
        "signed_reversal": reversal_primary,
        "signed_reversal_neighbor_outer_steps": reversal_outer,
        "signed_reversal_neighbor_halves": reversal_halves,
        "curvature": curvature_primary,
        "curvature_neighbor_outer_steps": curvature_outer,
        "curvature_neighbor_midpoint": curvature_midpoint,
    }
    for key, array in result.items():
        result[key] = np.where(finite, array, np.nan)
    return result


def _daily_windows(group: pd.DataFrame, column: str) -> np.ndarray:
    values = group[column].to_numpy(float)
    windows = np.lib.stride_tricks.sliding_window_view(values, 5)
    if windows.shape != (1453, 5):
        raise NonSlopeTrajectoryError("unexpected daily window population")
    return windows


def construct_panel(
    daily: pd.DataFrame, trajectory: pd.DataFrame, spec: dict[str, Any]
) -> pd.DataFrame:
    descriptors = _descriptors(spec)
    pieces: list[pd.DataFrame] = []
    for (view, denominator), group in daily.groupby(["market_view", "denominator"], sort=True):
        group = group.sort_values("trade_date").reset_index(drop=True)
        source = trajectory.loc[
            trajectory.market_view.eq(view) & trajectory.denominator.eq(denominator)
        ].sort_values("trade_date").reset_index(drop=True)
        expected_dates = group.trade_date.iloc[4:].reset_index(drop=True)
        if not source.trade_date.reset_index(drop=True).equals(expected_dates):
            raise NonSlopeTrajectoryError("daily/trajectory date alignment changed")
        item = source[KEYS + [
            "available_at", "hard_valid", "descriptor_coverage",
            "cy6_snapshot_sha256", "cy8_snapshot_selection_sha256",
        ]].copy()
        for descriptor in descriptors:
            for aggregation in ("median", "p40", "p60"):
                windows = _daily_windows(group, f"{descriptor}__{aggregation}")
                if aggregation == "median":
                    frozen = source[[f"{descriptor}__day_m{day}" for day in (5, 4, 3, 2, 1)]].to_numpy(float)
                    if not np.array_equal(windows, frozen, equal_nan=True):
                        raise NonSlopeTrajectoryError(f"five-day median lineage changed: {descriptor}")
                    item[f"{descriptor}__day_m1_level"] = windows[:, 4]
                operators = nonslope_operators(windows)
                for name, values in operators.items():
                    suffix = "" if aggregation == "median" else f"__{aggregation}"
                    item[f"{descriptor}__{name}{suffix}"] = values
        pieces.append(item)
    panel = pd.concat(pieces, ignore_index=True).sort_values(KEYS).reset_index(drop=True)
    role_names = [
        f"{descriptor}__{operator}" for descriptor in descriptors for operator in OPERATORS
    ]
    for _, index in panel.groupby(["market_view", "denominator"], sort=True).groups.items():
        ordered = panel.loc[index].sort_values("trade_date").index
        for role in role_names:
            series = panel.loc[ordered, role]
            panel.loc[ordered, f"{role}__pit_expanding_pct"] = causal_expanding_percentile(series).to_numpy()
            panel.loc[ordered, f"{role}__pit_3y_pct"] = causal_rolling_percentile(series).to_numpy()
            panel.loc[ordered, f"{role}__pit_3y_robust_z"] = causal_rolling_robust_z(series).to_numpy()
    for role in role_names:
        panel[f"{role}__relative_to_all_a"] = np.nan
        panel[f"{role}__view_rank"] = np.nan
        for (_, _), index in panel.groupby(["trade_date", "denominator"], sort=True).groups.items():
            cell = panel.loc[index]
            all_a = cell.loc[cell.market_view.eq("ALL_A"), role]
            if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
                continue
            panel.loc[index, f"{role}__relative_to_all_a"] = cell[role] - float(all_a.iloc[0])
            if cell[role].notna().sum() >= 3:
                panel.loc[index, f"{role}__view_rank"] = cell[role].rank(method="average", pct=True)
    return panel


def _role_priority(spec: dict[str, Any]) -> list[str]:
    return [
        f"{descriptor}__{operator}"
        for descriptor in spec["gates"]["descriptor_priority"]
        for operator in spec["gates"]["operator_priority"]
    ]


def _components(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    remaining = set(str(column) for column in correlation.columns)
    components: list[list[str]] = []
    while remaining:
        seed = sorted(remaining)[0]
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            for other in correlation.columns:
                other = str(other)
                value = correlation.loc[current, other]
                if other not in component and np.isfinite(value) and abs(float(value)) >= threshold:
                    stack.append(other)
        components.append(sorted(component))
    return sorted(components, key=lambda values: values[0])


def diagnostics(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    roles = _role_priority(spec)
    details: dict[str, Any] = {}
    for role in roles:
        descriptor, operator = role.split("__", 1)
        definition_neighbors = {
            "ordinal_progression": (
                f"{descriptor}__ordinal_progression_neighbor_all_pairs",
                f"{descriptor}__ordinal_progression_neighbor_rank_time",
            ),
            "signed_reversal": (
                f"{descriptor}__signed_reversal_neighbor_outer_steps",
                f"{descriptor}__signed_reversal_neighbor_halves",
            ),
            "curvature": (
                f"{descriptor}__curvature_neighbor_outer_steps",
                f"{descriptor}__curvature_neighbor_midpoint",
            ),
        }[operator]
        definition_values: dict[str, list[float]] = {name: [] for name in definition_neighbors}
        aggregation_values: dict[str, list[float]] = {agg: [] for agg in ("p40", "p60")}
        coverage: dict[str, float] = {}
        for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
            label = f"{view}:{denominator}"
            coverage[label] = float(group[role].notna().mean())
            for neighbor in definition_neighbors:
                definition_values[neighbor].append(_spearman(group[role], group[neighbor]))
            for aggregation in aggregation_values:
                aggregation_values[aggregation].append(
                    _spearman(group[role], group[f"{role}__{aggregation}"])
                )
        definition_medians = {
            name: float(np.nanmedian(values)) for name, values in definition_values.items()
        }
        aggregation_medians = {
            name: float(np.nanmedian(values)) for name, values in aggregation_values.items()
        }
        denominator_rhos: dict[str, float] = {}
        for view, group in panel.groupby("market_view", sort=True):
            wide = group.pivot(index="trade_date", columns="denominator", values=role)
            denominator_rhos[str(view)] = _spearman(wide.ALL_STATUS, wide.NON_ST)
        denominator_median = float(np.nanmedian(list(denominator_rhos.values())))
        year_cells: dict[str, Any] = {}
        year_pass = True
        reversal_sign_pass = True
        for (view, denominator, year), group in panel.groupby(
            ["market_view", "denominator", panel.trade_date.dt.year], sort=True
        ):
            values = group[role].dropna()
            if len(values) < gates["view_year_minimum_observations"]:
                year_pass = False
                continue
            nondegenerate = bool(values.nunique() >= 2)
            signs = sorted(float(value) for value in values.unique() if value != 0)
            both_signs = bool(-1.0 in signs and 1.0 in signs) if operator == "signed_reversal" else True
            year_pass &= nondegenerate
            reversal_sign_pass &= both_signs
            year_cells[f"{view}:{denominator}:{year}"] = {
                "n": int(len(values)), "nondegenerate": nondegenerate,
                "both_nonzero_reversal_signs": both_signs,
            }
        post_warmup = panel[role].notna().groupby(
            [panel.market_view, panel.denominator]
        ).cumsum() >= 504
        pit_coverage = float(panel.loc[post_warmup, f"{role}__pit_3y_pct"].notna().mean())
        relative_expected = panel.market_view.ne("ALL_A") & panel[role].notna()
        relative_coverage = float(
            panel.loc[relative_expected, f"{role}__relative_to_all_a"].notna().mean()
        )
        level_by_group = {
            f"{view}:{denominator}": _spearman(group[role], group[f"{descriptor}__day_m1_level"])
            for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True)
        }
        level_redundancy = float(np.nanmedian(np.abs(list(level_by_group.values()))))
        passed = bool(
            min(coverage.values()) >= gates["raw_coverage"]
            and min(definition_medians.values()) >= gates["worst_median_operator_neighbor_spearman"]
            and min(aggregation_medians.values()) >= gates["worst_median_aggregation_neighbor_spearman"]
            and denominator_median >= gates["all_status_vs_non_st_median_spearman"]
            and year_pass and reversal_sign_pass
            and pit_coverage >= gates["pit_and_relative_expected_coverage"]
            and relative_coverage >= gates["pit_and_relative_expected_coverage"]
        )
        details[role] = {
            "descriptor": descriptor,
            "operator": operator,
            "minimum_raw_coverage": min(coverage.values()),
            "definition_neighbor_median_spearman": definition_medians,
            "aggregation_neighbor_median_spearman": aggregation_medians,
            "all_status_vs_non_st_by_view": denominator_rhos,
            "all_status_vs_non_st_median_spearman": denominator_median,
            "view_year_cells": year_cells,
            "all_view_year_cells_nondegenerate": year_pass,
            "reversal_both_nonzero_signs_each_cell": reversal_sign_pass,
            "pit_expected_coverage": pit_coverage,
            "relative_expected_coverage": relative_coverage,
            "same_session_level_by_group": level_by_group,
            "same_session_level_median_absolute_spearman": level_redundancy,
            "representation_gate_pass": passed,
        }
    all_a = panel.loc[
        panel.market_view.eq("ALL_A") & panel.denominator.eq("ALL_STATUS"), roles
    ]
    correlation = all_a.corr(method="spearman", min_periods=100)
    components = _components(correlation, gates["latent_component_edge_absolute_spearman"])
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in roles:
        item = details[role]
        if not item["representation_gate_pass"]:
            excluded[role] = "representation_gate_failed"
            continue
        if item["same_session_level_median_absolute_spearman"] >= gates[
            "same_session_level_redundancy_absolute_spearman"
        ]:
            excluded[role] = "same_session_level_redundant"
            continue
        blockers = [
            other for other in accepted
            if np.isfinite(correlation.loc[role, other])
            and abs(float(correlation.loc[role, other])) >= gates["latent_component_edge_absolute_spearman"]
        ]
        if blockers:
            excluded[role] = "trajectory_redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    operator_summary = {
        operator: {
            "attempted": sum(item["operator"] == operator for item in details.values()),
            "representation_pass": sum(
                item["operator"] == operator and item["representation_gate_pass"]
                for item in details.values()
            ),
            "minimal_accepted": sum(role.endswith(f"__{operator}") for role in accepted),
        }
        for operator in OPERATORS
    }
    return {
        "roles": details,
        "operator_summary": operator_summary,
        "primary_spearman_all_a_all_status": correlation.to_dict(),
        "latent_components": components,
        "minimal_panel": {"accepted_roles": accepted, "excluded_roles": excluded},
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-MIN-PATH-002 non-slope five-day intraday trajectories",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Output: {result['population']['rows']:,} rows, {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Raw minute rows, OLS/endpoint/precomputed-shape fields, outcomes, strategy fields, and CY-011 read: **none**.",
        "- Stable shapes are trajectory descriptors, not supply/demand mechanisms or usefulness.",
        "",
        "## Operator results",
        "",
        "| Operator | Attempted | Representation pass | Minimal accepted |",
        "|---|---:|---:|---:|",
    ]
    for operator in OPERATORS:
        item = result["diagnostics"]["operator_summary"][operator]
        lines.append(
            f"| {operator} | {item['attempted']} | {item['representation_pass']} | {item['minimal_accepted']} |"
        )
    lines.extend([
        "",
        f"Minimal nonredundant roles: `{', '.join(result['diagnostics']['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "",
        "## Role gates",
        "",
        "| Role | Worst definition rho | Worst aggregation rho | ST rho | Level rho | Gate | Disposition |",
        "|---|---:|---:|---:|---:|---|---|",
    ])
    accepted = set(result["diagnostics"]["minimal_panel"]["accepted_roles"])
    excluded = result["diagnostics"]["minimal_panel"]["excluded_roles"]
    for role in _role_priority(_load_spec()):
        item = result["diagnostics"]["roles"][role]
        disposition = "ACCEPT" if role in accepted else excluded.get(role, "EXCLUDE")
        lines.append(
            f"| `{role}` | {min(item['definition_neighbor_median_spearman'].values()):.3f} | "
            f"{min(item['aggregation_neighbor_median_spearman'].values()):.3f} | "
            f"{item['all_status_vs_non_st_median_spearman']:.3f} | "
            f"{item['same_session_level_median_absolute_spearman']:.3f} | "
            f"{'PASS' if item['representation_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Daily input SHA-256: `{result['hashes']['daily_panel_sha256']}`",
        f"- Source trajectory SHA-256: `{result['hashes']['source_trajectory_panel_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily, trajectory = load_bound_inputs(spec)
    panel = construct_panel(daily, trajectory, spec)
    diag = diagnostics(panel, spec)
    output = panel.copy()
    output["trade_date"] = output.trade_date.dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    passed = sum(item["representation_gate_pass"] for item in diag["roles"].values())
    accepted = len(diag["minimal_panel"]["accepted_roles"])
    result = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{passed}_OF_36_REPRESENTATIONS_PASS_{accepted}_MINIMAL",
        "usefulness_claim": "NONE",
        "mechanism_claim": "NONE",
        "raw_minute_rows_read": 0,
        "forbidden_old_shape_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "population": {
            "rows": int(len(output)),
            "first_date": str(output.trade_date.min()),
            "last_date": str(output.trade_date.max()),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
            "roles_attempted": 36,
        },
        "diagnostics": diag,
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "scientific_design_sha256": spec["inherited_scientific_design_sha256"],
            "daily_panel_sha256": sha256_file(DAILY_PATH),
            "source_trajectory_panel_sha256": sha256_file(SOURCE_TRAJECTORY_PATH),
            "source_result_sha256": sha256_file(SOURCE_RESULT_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    cleaned = _clean(result)
    RESULT_PATH.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return cleaned


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "status": final["status"],
        "operator_summary": final["diagnostics"]["operator_summary"],
        "minimal_roles": final["diagnostics"]["minimal_panel"]["accepted_roles"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
