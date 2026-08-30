#!/usr/bin/env python3
"""Build historical dynamics of full-market objective-breakout levels."""

from __future__ import annotations

import hashlib
import json
import math
import resource
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)

SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DIFF-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DYN-001_panel.csv"
STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DYN-001_stability_audit.csv"
EXTERNAL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DYN-001_external_geometry_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DIFF-DYN-001_representation.md"
EXPECTED_SPEC_SHA256 = "3c095e17a76b19cbc82fece8dc458cc3e16bc02c859175bf83f7a7c1b8416d14"
KEYS = ["trade_date", "market_view", "denominator"]
OPERATORS = ("change", "acceleration")
CONTROL_LEVELS = {
    "discovery": "breadth_net_new_high_low60",
    "leadership_concentration": "leadership_positive_mass_top10",
}


class BreakoutDiffusionDynamicsError(RuntimeError):
    """Fail-closed historical breakout-diffusion dynamics error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


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
        raise BreakoutDiffusionDynamicsError("dynamic spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_TEMPORAL_REPRESENTATION_ESTIMATES"
        or spec["outcome_access"] is not False
    ):
        raise BreakoutDiffusionDynamicsError("dynamic activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise BreakoutDiffusionDynamicsError(f"input identity mismatch: {name}")
    parent = json.loads(_resolve(spec["inputs"]["level_result"]["path"]).read_text())
    if (
        parent["status"] != spec["parent_activation"]["required_status"]
        or parent["minimal_panel"]["accepted_roles"]
        != spec["parent_activation"]["required_direct_roles"]
        or parent["minimal_panel"]["excluded_roles"]
        != {"equal_industry_formation": "internally_redundant_with:formation_participation"}
        or parent["claim"] != "REPRESENTATION_AND_EXTERNAL_GEOMETRY_ONLY"
        or parent["outcome_or_strategy_fields_read"]
        or parent["post_2023_read"]
        or parent["cy011_read"]
    ):
        raise BreakoutDiffusionDynamicsError("parent level activation changed")
    breadth = json.loads(_resolve(spec["inputs"]["breadth_result"]["path"]).read_text())
    if breadth["minimal_panel"]["accepted_roles"] != [
        "new_high_low",
        "leadership_concentration",
    ]:
        raise BreakoutDiffusionDynamicsError("breadth-control activation changed")
    return spec


def _theil_sen(values: np.ndarray) -> float:
    if not np.isfinite(values).all():
        return float("nan")
    slopes = [
        (float(values[later]) - float(values[earlier])) / (later - earlier)
        for earlier in range(len(values))
        for later in range(earlier + 1, len(values))
    ]
    return float(np.median(slopes))


def _rolling_slope(values: pd.Series, horizon: int, method: str) -> pd.Series:
    width = horizon + 1
    raw = values.to_numpy(dtype=float)
    output = np.full(len(raw), np.nan, dtype=float)
    time = np.arange(width, dtype=float)
    centered = time - time.mean()
    denominator = float(np.square(centered).sum())
    for position in range(horizon, len(raw)):
        window = raw[position - horizon : position + 1]
        if not np.isfinite(window).all():
            continue
        if method == "ols":
            output[position] = float(centered @ window / denominator)
        elif method == "theilsen":
            output[position] = _theil_sen(window)
        else:
            raise BreakoutDiffusionDynamicsError(f"unknown slope method: {method}")
    return pd.Series(output, index=values.index, dtype=float)


def temporal_operators(values: pd.Series) -> dict[str, pd.Series]:
    """Return the two primaries and their frozen historical neighbors."""
    values = values.astype(float)
    change3 = (values - values.shift(3)) / 3.0
    change5 = (values - values.shift(5)) / 5.0
    change10 = (values - values.shift(10)) / 10.0
    ols5 = _rolling_slope(values, 5, "ols")
    theilsen5 = _rolling_slope(values, 5, "theilsen")
    return {
        "change": change5,
        "change_neighbor_h3": change3,
        "change_neighbor_h10": change10,
        "change_neighbor_ols5": ols5,
        "change_neighbor_theilsen5": theilsen5,
        "acceleration": change5 - change5.shift(5),
        "acceleration_neighbor_h3": change3 - change3.shift(3),
        "acceleration_neighbor_h10": change10 - change10.shift(10),
        "acceleration_neighbor_ols5": ols5 - ols5.shift(5),
        "acceleration_neighbor_theilsen5": theilsen5 - theilsen5.shift(5),
    }


def _load_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    level_columns = [*KEYS, "decision_at", "available_at", "snapshot_id", *spec["roles"].values()]
    breadth_columns = [*KEYS, *CONTROL_LEVELS.values()]
    levels = pd.read_csv(_resolve(spec["inputs"]["level_panel"]["path"]), usecols=level_columns)
    breadth = pd.read_csv(
        _resolve(spec["inputs"]["breadth_panel"]["path"]), usecols=breadth_columns
    )
    for label, frame in (("level", levels), ("breadth", breadth)):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
        if frame.duplicated(KEYS).any():
            raise BreakoutDiffusionDynamicsError(f"duplicate {label} key")
        if frame["trade_date"].max() > pd.Timestamp("2023-12-31"):
            raise BreakoutDiffusionDynamicsError(f"post-2023 {label} row")
    population = spec["population"]
    if (
        len(levels) != population["expected_rows"]
        or str(levels["trade_date"].min().date()) != population["date_start"]
        or str(levels["trade_date"].max().date()) != population["date_end"]
        or set(levels["market_view"]) != set(population["market_views"])
        or set(levels["denominator"]) != set(population["denominators"])
    ):
        raise BreakoutDiffusionDynamicsError("level population changed")
    counts = levels.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not counts.eq(population["expected_rows_per_group"]).all():
        raise BreakoutDiffusionDynamicsError("level group population changed")
    decision = pd.to_datetime(levels["decision_at"], errors="raise", utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    available = pd.to_datetime(levels["available_at"], errors="raise", utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    if (
        not decision.equals(available)
        or not decision.dt.strftime("%H:%M:%S").eq("15:00:00").all()
        or not (decision.dt.date == levels["trade_date"].dt.date).all()
    ):
        raise BreakoutDiffusionDynamicsError("completed-close availability changed")
    if set(breadth["trade_date"]) - set(levels["trade_date"]):
        raise BreakoutDiffusionDynamicsError("breadth date outside level domain")
    return (
        levels.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True),
        breadth.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True),
    )


def _relative_coordinates(panel: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        panel[f"{column}_relative_to_all"] = np.nan
        panel[f"{column}_relative_view_rank_pct"] = np.nan
        for _, index in panel.groupby(["trade_date", "denominator"], sort=True).groups.items():
            cell = panel.loc[index]
            all_a = cell.loc[cell["market_view"].eq("ALL_A"), column]
            if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
                continue
            panel.loc[index, f"{column}_relative_to_all"] = cell[column] - float(all_a.iloc[0])
            if cell[column].notna().sum() >= 3:
                panel.loc[index, f"{column}_relative_view_rank_pct"] = cell[column].rank(
                    method="average", pct=True
                )


def construct_panel(
    levels: pd.DataFrame, breadth: pd.DataFrame, spec: dict[str, Any]
) -> pd.DataFrame:
    base = levels.copy()
    breadth_renamed = breadth.rename(
        columns={column: f"control_level__{name}" for name, column in CONTROL_LEVELS.items()}
    )
    base = base.merge(breadth_renamed, on=KEYS, how="left", validate="one_to_one")
    pieces: list[pd.DataFrame] = []
    role_columns: list[str] = []
    control_columns: list[str] = []
    for _, group in base.groupby(["market_view", "denominator"], sort=True):
        group = group.sort_values("trade_date").copy()
        item = group[[*KEYS, "decision_at", "available_at", "snapshot_id"]].copy()
        for role, source in spec["roles"].items():
            item[f"{role}__level"] = group[source].to_numpy(dtype=float)
            operators = temporal_operators(group[source])
            for name, values in operators.items():
                column = f"{role}__{name}"
                item[column] = values.to_numpy(dtype=float)
                if name in OPERATORS:
                    role_columns.append(column)
        for control in CONTROL_LEVELS:
            source = f"control_level__{control}"
            operators = temporal_operators(group[source])
            for operator in OPERATORS:
                column = f"control__{control}__{operator}"
                item[column] = operators[operator].to_numpy(dtype=float)
                control_columns.append(column)
        pieces.append(item)
    panel = pd.concat(pieces, ignore_index=True).sort_values(KEYS).reset_index(drop=True)
    role_columns = list(dict.fromkeys(role_columns))
    control_columns = list(dict.fromkeys(control_columns))
    for _, index in panel.groupby(["market_view", "denominator"], sort=True).groups.items():
        ordered = panel.loc[index].sort_values("trade_date").index
        for column in [*role_columns, *control_columns]:
            series = panel.loc[ordered, column]
            panel.loc[ordered, f"{column}_pit_expanding_pct"] = causal_expanding_percentile(
                series
            ).to_numpy()
            panel.loc[ordered, f"{column}_pit_3y_pct"] = causal_rolling_percentile(
                series
            ).to_numpy()
            panel.loc[ordered, f"{column}_pit_3y_robust_z"] = causal_rolling_robust_z(
                series
            ).to_numpy()
    _relative_coordinates(panel, [*role_columns, *control_columns])
    panel["dynamic_decision_at"] = panel["decision_at"]
    panel["dynamic_available_at"] = panel["available_at"]
    return panel


def _spearman(left: pd.Series, right: pd.Series) -> tuple[float, int]:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan"), len(clean)
    return float(clean.corr(method="spearman").iloc[0, 1]), len(clean)


def _neighbor_columns(role: str, operator: str) -> list[str]:
    return [
        f"{role}__{operator}_neighbor_h3",
        f"{role}__{operator}_neighbor_h10",
        f"{role}__{operator}_neighbor_ols5",
        f"{role}__{operator}_neighbor_theilsen5",
    ]


def _expected_pit_mask(group: pd.DataFrame, column: str) -> pd.Series:
    return group[column].notna().astype(int).rolling(756, min_periods=1).sum().ge(504)


def _role_diagnostics(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    gates = spec["gates"]
    details: dict[str, Any] = {}
    audit_rows: list[dict[str, Any]] = []
    blocks = spec["population"]["historical_blocks"]
    for role_operator in gates["minimal_role_priority"]:
        role, operator = role_operator.split("__", 1)
        primary = role_operator
        neighbors = _neighbor_columns(role, operator)
        coverage: dict[str, float] = {}
        full_values: dict[str, list[float]] = {neighbor: [] for neighbor in neighbors}
        phase_values: dict[str, list[float]] = {neighbor: [] for neighbor in neighbors}
        block_values: dict[str, dict[str, list[float]]] = {
            block: {neighbor: [] for neighbor in neighbors} for block in blocks
        }
        for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
            group_name = f"{view}:{denominator}"
            coverage[group_name] = float(group[primary].notna().mean())
            for neighbor in neighbors:
                rho, n = _spearman(group[primary], group[neighbor])
                full_values[neighbor].append(rho)
                audit_rows.append(
                    {
                        "role": role,
                        "operator": operator,
                        "neighbor": neighbor.rsplit("__", 1)[-1],
                        "scope": "FULL",
                        "group": group_name,
                        "n": n,
                        "spearman": rho,
                    }
                )
                phase_group = group.loc[group[primary].notna()].iloc[::5]
                phase_rho, phase_n = _spearman(phase_group[primary], phase_group[neighbor])
                phase_values[neighbor].append(phase_rho)
                audit_rows.append(
                    {
                        "role": role,
                        "operator": operator,
                        "neighbor": neighbor.rsplit("__", 1)[-1],
                        "scope": "PHASE_ZERO",
                        "group": group_name,
                        "n": phase_n,
                        "spearman": phase_rho,
                    }
                )
                for block, years in blocks.items():
                    cell = group.loc[group["trade_date"].dt.year.isin(years)]
                    block_rho, block_n = _spearman(cell[primary], cell[neighbor])
                    block_values[block][neighbor].append(block_rho)
                    audit_rows.append(
                        {
                            "role": role,
                            "operator": operator,
                            "neighbor": neighbor.rsplit("__", 1)[-1],
                            "scope": f"BLOCK_{block}",
                            "group": group_name,
                            "n": block_n,
                            "spearman": block_rho,
                        }
                    )
        full_medians = {
            neighbor: float(np.nanmedian(values)) for neighbor, values in full_values.items()
        }
        phase_medians = {
            neighbor: float(np.nanmedian(values)) for neighbor, values in phase_values.items()
        }
        block_medians = {
            block: {
                neighbor: float(np.nanmedian(values)) for neighbor, values in by_neighbor.items()
            }
            for block, by_neighbor in block_values.items()
        }
        denominator_rhos: dict[str, float] = {}
        for view, group in panel.groupby("market_view", sort=True):
            wide = group.pivot(index="trade_date", columns="denominator", values=primary)
            denominator_rhos[str(view)], _ = _spearman(wide["ALL_STATUS"], wide["NON_ST"])
        denominator_median = float(np.nanmedian(list(denominator_rhos.values())))
        year_cells: dict[str, Any] = {}
        year_pass = True
        for (view, denominator, year), group in panel.groupby(
            ["market_view", "denominator", panel["trade_date"].dt.year], sort=True
        ):
            values = group[primary].dropna()
            supported = len(values) >= gates["view_year_minimum_observations"]
            nondegenerate = bool(values.nunique() >= 2)
            year_pass &= supported and nondegenerate
            year_cells[f"{view}:{denominator}:{year}"] = {
                "n": len(values),
                "nondegenerate": nondegenerate,
                "gate_pass": bool(supported and nondegenerate),
            }
        pit_expected = pd.Series(False, index=panel.index)
        for _, index in panel.groupby(["market_view", "denominator"], sort=True).groups.items():
            ordered = panel.loc[index].sort_values("trade_date")
            pit_expected.loc[ordered.index] = _expected_pit_mask(ordered, primary).to_numpy()
        pit_coverage = float(panel.loc[pit_expected, f"{primary}_pit_3y_pct"].notna().mean())
        relative_expected = panel["market_view"].ne("ALL_A") & panel[primary].notna()
        relative_coverage = float(
            panel.loc[relative_expected, f"{primary}_relative_to_all"].notna().mean()
        )
        rank_expected = panel[primary].notna()
        rank_coverage = float(
            panel.loc[rank_expected, f"{primary}_relative_view_rank_pct"].notna().mean()
        )
        level_by_group: dict[str, float] = {}
        for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
            rho, _ = _spearman(group[primary], group[f"{role}__level"])
            level_by_group[f"{view}:{denominator}"] = rho
        level_redundancy = float(np.nanmedian(np.abs(list(level_by_group.values()))))
        construction_pass = bool(
            min(coverage.values()) >= gates["raw_coverage"]
            and min(full_medians.values()) >= gates["worst_full_sample_neighbor_median_spearman"]
            and min(value for block in block_medians.values() for value in block.values())
            >= gates["worst_block_neighbor_median_spearman"]
            and min(phase_medians.values()) >= gates["phase_zero_worst_neighbor_median_spearman"]
            and denominator_median >= gates["all_status_vs_non_st_median_spearman"]
            and year_pass
            and pit_coverage >= gates["pit_expected_coverage"]
            and relative_coverage >= gates["relative_expected_coverage"]
            and rank_coverage >= gates["relative_expected_coverage"]
        )
        details[role_operator] = {
            "role": role,
            "operator": operator,
            "minimum_raw_coverage": min(coverage.values()),
            "full_neighbor_median_spearman": full_medians,
            "worst_full_neighbor_median_spearman": min(full_medians.values()),
            "block_neighbor_median_spearman": block_medians,
            "worst_block_neighbor_median_spearman": min(
                value for block in block_medians.values() for value in block.values()
            ),
            "phase_zero_neighbor_median_spearman": phase_medians,
            "worst_phase_zero_neighbor_median_spearman": min(phase_medians.values()),
            "all_status_vs_non_st_by_view": denominator_rhos,
            "all_status_vs_non_st_median_spearman": denominator_median,
            "view_year_cells": year_cells,
            "all_view_year_cells_nondegenerate": year_pass,
            "pit_expected_coverage": pit_coverage,
            "relative_expected_coverage": relative_coverage,
            "relative_rank_expected_coverage": rank_coverage,
            "same_session_level_by_group": level_by_group,
            "same_session_level_median_absolute_spearman": level_redundancy,
            "construction_gate_pass": construction_pass,
        }
    return details, pd.DataFrame(audit_rows)


def adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    clean = frame[[target, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(clean)
    p = len(controls)
    if n <= p + 2 or clean[target].nunique() < 2:
        return float("nan")
    ranked = clean.rank(method="average", pct=True)
    y = ranked[target].to_numpy(dtype=float)
    x = np.column_stack([np.ones(n), ranked[controls].to_numpy(dtype=float)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    total = float(np.square(y - y.mean()).sum())
    if total == 0.0:
        return float("nan")
    r2 = 1.0 - float(np.square(y - fitted).sum()) / total
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _external_geometry(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    controls = spec["external_controls"]
    suffixes = {
        "absolute": "",
        "pit_3y_pct": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
    }
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for role_operator in spec["gates"]["minimal_role_priority"]:
        _, operator = role_operator.split("__", 1)
        role_rows: list[dict[str, Any]] = []
        for block, years in spec["population"]["historical_blocks"].items():
            block_panel = panel.loc[panel["trade_date"].dt.year.isin(years)]
            for coordinate, suffix in suffixes.items():
                views = (
                    controls["relative_views"]
                    if coordinate == "relative_to_all"
                    else controls["absolute_and_pit_views"]
                )
                target = f"{role_operator}{suffix}"
                control_columns = [
                    f"control__{name}__{operator}{suffix}" for name in CONTROL_LEVELS
                ]
                for denominator in controls["denominators"]:
                    for view in views:
                        cell = block_panel.loc[
                            block_panel["denominator"].eq(denominator)
                            & block_panel["market_view"].eq(view)
                        ]
                        complete = cell[[target, *control_columns]].dropna()
                        n = len(complete)
                        rhos = [
                            _spearman(complete[target], complete[column])[0]
                            for column in control_columns
                        ]
                        joint = adjusted_rank_r2(complete, target, control_columns)
                        passed = bool(
                            n >= controls["minimum_complete_observations_per_cell"]
                            and all(np.isfinite(rhos))
                            and max(abs(value) for value in rhos)
                            <= controls["maximum_absolute_pairwise_spearman"]
                            and np.isfinite(joint)
                            and joint <= controls["maximum_joint_adjusted_rank_r2"]
                        )
                        record = {
                            "role_operator": role_operator,
                            "block": block,
                            "coordinate": coordinate,
                            "market_view": view,
                            "denominator": denominator,
                            "n": n,
                            "rho_discovery_dynamic": rhos[0],
                            "rho_leadership_dynamic": rhos[1],
                            "joint_adjusted_rank_r2": joint,
                            "gate_pass": passed,
                        }
                        rows.append(record)
                        role_rows.append(record)
        summary[role_operator] = {
            "cells": len(role_rows),
            "minimum_n": min(row["n"] for row in role_rows),
            "maximum_absolute_pairwise_spearman": max(
                max(abs(row["rho_discovery_dynamic"]), abs(row["rho_leadership_dynamic"]))
                for row in role_rows
                if np.isfinite(row["rho_discovery_dynamic"])
                and np.isfinite(row["rho_leadership_dynamic"])
            ),
            "maximum_joint_adjusted_rank_r2": max(
                row["joint_adjusted_rank_r2"]
                for row in role_rows
                if np.isfinite(row["joint_adjusted_rank_r2"])
            ),
            "all_external_cells_pass": all(row["gate_pass"] for row in role_rows),
        }
    return summary, pd.DataFrame(rows)


def _scalar_cases(
    levels: pd.DataFrame, panel: pd.DataFrame, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for role_operator in spec["gates"]["minimal_role_priority"]:
        role, operator = role_operator.split("__", 1)
        for row in panel.loc[panel[role_operator].notna(), [*KEYS, role_operator]].itertuples(
            index=False
        ):
            identity = (
                f"MKT-BREAKOUT-DIFF-DYN-001|{row.trade_date.date()}|{row.market_view}|"
                f"{row.denominator}|{role_operator}"
            )
            candidates.append(
                {
                    "selection_hash": hashlib.sha256(identity.encode()).hexdigest(),
                    "trade_date": row.trade_date,
                    "market_view": row.market_view,
                    "denominator": row.denominator,
                    "role": role,
                    "operator": operator,
                    "constructed": float(getattr(row, role_operator)),
                }
            )
    selected = sorted(candidates, key=lambda item: item["selection_hash"])[:5]
    output: list[dict[str, Any]] = []
    for case in selected:
        source_column = spec["roles"][case["role"]]
        group = levels.loc[
            levels["market_view"].eq(case["market_view"])
            & levels["denominator"].eq(case["denominator"])
        ].sort_values("trade_date")
        positions = np.flatnonzero(group["trade_date"].eq(case["trade_date"]).to_numpy())
        if len(positions) != 1:
            raise BreakoutDiffusionDynamicsError("scalar source position changed")
        position = int(positions[0])
        values = group[source_column].to_numpy(dtype=float)
        if case["operator"] == "change":
            scalar = (values[position] - values[position - 5]) / 5.0
        else:
            scalar = (values[position] - values[position - 5]) / 5.0 - (
                values[position - 5] - values[position - 10]
            ) / 5.0
        exact = bool(float(scalar) == case["constructed"])
        if not exact:
            raise BreakoutDiffusionDynamicsError("scalar temporal operator disagreement")
        output.append(
            {
                "selection_hash": case["selection_hash"],
                "trade_date": str(case["trade_date"].date()),
                "market_view": case["market_view"],
                "denominator": case["denominator"],
                "role": case["role"],
                "operator": case["operator"],
                "scalar": scalar,
                "exact_match": True,
            }
        )
    if len(output) != 5:
        raise BreakoutDiffusionDynamicsError("five scalar cases unavailable")
    return output


def _minimal_panel(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    diagnostics: dict[str, Any],
    external: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, float]]]:
    priority = spec["gates"]["minimal_role_priority"]
    all_a = panel.loc[
        panel["market_view"].eq("ALL_A") & panel["denominator"].eq("ALL_STATUS"),
        priority,
    ]
    correlation = all_a.corr(method="spearman", min_periods=150)
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role_operator in priority:
        item = diagnostics[role_operator]
        if not item["construction_gate_pass"]:
            excluded[role_operator] = "representation_gate_failed"
            continue
        if (
            item["same_session_level_median_absolute_spearman"]
            >= spec["gates"]["same_session_level_redundancy_absolute_spearman"]
        ):
            excluded[role_operator] = "same_session_level_redundant"
            continue
        if not external[role_operator]["all_external_cells_pass"]:
            excluded[role_operator] = "generic_breadth_dynamic_redundancy_or_support_failed"
            continue
        blockers = [
            other
            for other in accepted
            if np.isfinite(correlation.loc[role_operator, other])
            and abs(float(correlation.loc[role_operator, other]))
            >= spec["gates"]["internal_redundancy_absolute_spearman"]
        ]
        if blockers:
            excluded[role_operator] = "internally_redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role_operator)
    correlation_dict = {
        str(row): {
            str(column): float(correlation.loc[row, column])
            if np.isfinite(correlation.loc[row, column])
            else float("nan")
            for column in correlation.columns
        }
        for row in correlation.index
    }
    return {"accepted_roles": accepted, "excluded_roles": excluded}, correlation_dict


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    accepted = set(result["minimal_panel"]["accepted_roles"])
    lines = [
        "# MKT-BREAKOUT-DIFF-DYN-001 historical temporal representations",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Panel: {result['population']['rows']:,} rows, "
        f"{result['population']['first_date']}..{result['population']['last_date']}.",
        f"- Construction-pass roles: {len(result['construction_pass_roles'])}/14; "
        f"minimal direct roles: {len(accepted)}.",
        "- Inputs stop at each completed 15:00 close. Future state, outcomes, strategy "
        "fields, raw security/minute data, post-2023 data, and CY-011 were not read.",
        "- Stable historical shape is not persistence, prediction, habitat, or "
        "strategy usefulness.",
        "",
        "## Fixed gates",
        "",
        "| Role | Full neighbor | Block neighbor | Phase neighbor | ST rho | Level rho | "
        "External max rho/R2 | Disposition |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for role_operator in spec["gates"]["minimal_role_priority"]:
        item = result["role_diagnostics"][role_operator]
        ext = result["external_geometry"][role_operator]
        disposition = (
            "RETAIN"
            if role_operator in accepted
            else result["minimal_panel"]["excluded_roles"][role_operator]
        )
        lines.append(
            f"| {role_operator} | {item['worst_full_neighbor_median_spearman']:.3f} | "
            f"{item['worst_block_neighbor_median_spearman']:.3f} | "
            f"{item['worst_phase_zero_neighbor_median_spearman']:.3f} | "
            f"{item['all_status_vs_non_st_median_spearman']:.3f} | "
            f"{item['same_session_level_median_absolute_spearman']:.3f} | "
            f"{ext['maximum_absolute_pairwise_spearman']:.3f}/"
            f"{ext['maximum_joint_adjusted_rank_r2']:.3f} | "
            f"{disposition} |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Runner SHA-256: `{result['hashes']['runner_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
            f"- Stability audit SHA-256: `{result['hashes']['stability_audit_sha256']}`",
            f"- External audit SHA-256: `{result['hashes']['external_audit_sha256']}`",
            "- Five independently reconstructed scalar operators match exactly.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    levels, breadth = _load_inputs(spec)
    panel = construct_panel(levels, breadth, spec)
    diagnostics, stability = _role_diagnostics(panel, spec)
    external, external_audit = _external_geometry(panel, spec)
    minimal, correlation = _minimal_panel(panel, spec, diagnostics, external)
    scalar_cases = _scalar_cases(levels, panel, spec)

    output = panel.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    stability.to_csv(STABILITY_PATH, index=False, float_format="%.12g", lineterminator="\n")
    external_audit.to_csv(EXTERNAL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    construction_pass = [
        role
        for role in spec["gates"]["minimal_role_priority"]
        if diagnostics[role]["construction_gate_pass"]
    ]
    peak_rss_bytes = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform != "darwin":
        peak_rss_bytes *= 1024
    durable_bytes = sum(path.stat().st_size for path in (PANEL_PATH, STABILITY_PATH, EXTERNAL_PATH))
    if peak_rss_bytes > spec["resource_budget"]["peak_rss_ceiling_gib"] * (
        1024**3
    ) or durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * (1024**2):
        raise BreakoutDiffusionDynamicsError("resource boundary exceeded")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": (
            f"COMPLETE_{len(construction_pass)}_OF_14_REPRESENTATIONS_PASS_"
            f"{len(minimal['accepted_roles'])}_MINIMAL"
        ),
        "usefulness_claim": "NONE",
        "mechanism_claim": "NONE",
        "future_values_read": False,
        "strategy_or_outcome_fields_read": [],
        "raw_security_rows_read": 0,
        "raw_minute_rows_read": 0,
        "post_2023_rows_read": 0,
        "cy011_read": False,
        "population": {
            "rows": len(output),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "roles_attempted": 14,
        },
        "construction_pass_roles": construction_pass,
        "role_diagnostics": diagnostics,
        "external_geometry": external,
        "primary_spearman_all_a_all_status": correlation,
        "minimal_panel": minimal,
        "scalar_cases": scalar_cases,
        "resource_audit": {
            "peak_rss_ceiling_bytes": int(
                spec["resource_budget"]["peak_rss_ceiling_gib"] * (1024**3)
            ),
            "durable_output_bytes_before_result_report": durable_bytes,
            "resource_gate_pass": True,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "runner_sha256": sha256_file(Path(__file__)),
            "level_panel_sha256": sha256_file(_resolve(spec["inputs"]["level_panel"]["path"])),
            "breadth_panel_sha256": sha256_file(_resolve(spec["inputs"]["breadth_panel"]["path"])),
            "panel_sha256": sha256_file(PANEL_PATH),
            "stability_audit_sha256": sha256_file(STABILITY_PATH),
            "external_audit_sha256": sha256_file(EXTERNAL_PATH),
        },
    }
    cleaned = _clean(result)
    RESULT_PATH.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(cleaned, spec), encoding="utf-8")
    return cleaned


if __name__ == "__main__":
    final = run()
    print(
        json.dumps(
            {
                "status": final["status"],
                "construction_pass_roles": final["construction_pass_roles"],
                "minimal_roles": final["minimal_panel"]["accepted_roles"],
                "panel_sha256": final["hashes"]["panel_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
