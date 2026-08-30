#!/usr/bin/env python3
"""Outcome-blind representation analysis for required-scale MKT-MIN-001."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.simplefilter("ignore", pd.errors.PerformanceWarning)


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPTS = PROGRAM / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)

ADAPTER_PATH = SCRIPTS / "vectorized_market_minute_adapter.py"
MODULE_SPEC = importlib.util.spec_from_file_location("vectorized_market_minute_adapter", ADAPTER_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
adapter = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(adapter)


SPEC_PATH = PROGRAM / "experiments/MKT-MIN-001_spec.json"
DAILY_PATH = PROGRAM / "artifacts/MKT-MIN-001_daily_market_panel.csv"
TRAJECTORY_PATH = PROGRAM / "artifacts/MKT-MIN-001_trajectory_panel.parquet"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-001_market_intraday_representation.md"

FAMILY_BY_DESCRIPTOR = {
    **{name: "price_path" for name in adapter.DESCRIPTOR_COLUMNS[:9]},
    **{name: "vwap_structure" for name in adapter.DESCRIPTOR_COLUMNS[9:16]},
    **{name: "selling_pressure" for name in adapter.DESCRIPTOR_COLUMNS[16:21]},
    **{name: "buying_pressure" for name in adapter.DESCRIPTOR_COLUMNS[21:25]},
    **{name: "volatility_oscillation" for name in adapter.DESCRIPTOR_COLUMNS[25:29]},
    **{name: "volume_path" for name in adapter.DESCRIPTOR_COLUMNS[29:33]},
    adapter.DESCRIPTOR_COLUMNS[33]: "auction_relation",
}


class MarketMinuteAnalysisError(RuntimeError):
    """Raised when a frozen analysis or representation gate is violated."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def trajectory_arrays(values: np.ndarray) -> dict[str, np.ndarray]:
    if values.ndim != 2 or values.shape[0] < 5:
        raise MarketMinuteAnalysisError("trajectory input requires dates x descriptors")
    windows = np.lib.stride_tricks.sliding_window_view(values, 5, axis=0)
    if windows.shape != (values.shape[0] - 4, values.shape[1], 5):
        raise MarketMinuteAnalysisError("unexpected five-day window orientation")
    x5 = np.arange(5, dtype=float) - 2.0
    x3 = np.arange(3, dtype=float) - 1.0
    slope5 = (windows * x5).sum(axis=2) / np.square(x5).sum()
    slope3 = (windows[:, :, -3:] * x3).sum(axis=2) / np.square(x3).sum()
    differences = np.diff(windows, axis=2)
    direction = np.sign(slope5)
    consistent = np.where(
        direction == 0,
        0.0,
        direction * (np.sign(differences) == direction[:, :, None]).mean(axis=2),
    )
    first_slope = differences[:, :, :2].mean(axis=2)
    last_slope = differences[:, :, -2:].mean(axis=2)
    reversal = np.where(
        np.sign(first_slope) * np.sign(last_slope) == -1,
        np.sign(last_slope),
        0.0,
    )
    return {
        "day_m5": windows[:, :, 0],
        "day_m4": windows[:, :, 1],
        "day_m3": windows[:, :, 2],
        "day_m2": windows[:, :, 3],
        "day_m1": windows[:, :, 4],
        "endpoint_change5": windows[:, :, 4] - windows[:, :, 0],
        "endpoint_slope5": (windows[:, :, 4] - windows[:, :, 0]) / 4.0,
        "ols_slope5": slope5,
        "ols_slope3": slope3,
        "signed_monotonic_fraction": consistent,
        "slope_acceleration": last_slope - first_slope,
        "reversal_shape": reversal,
    }


def _spearman(left: pd.Series, right: pd.Series) -> float:
    mask = np.isfinite(left.to_numpy(float)) & np.isfinite(right.to_numpy(float))
    if int(mask.sum()) < 3:
        return float("nan")
    a = left.loc[mask]
    b = right.loc[mask]
    if a.nunique() < 2 or b.nunique() < 2:
        return float("nan")
    return float(a.corr(b, method="spearman"))


def _components(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    names = list(correlation.columns)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            value = correlation.loc[left, right]
            if np.isfinite(value) and abs(float(value)) >= threshold:
                union(left, right)
    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(find(name), []).append(name)
    return sorted((sorted(values) for values in grouped.values()), key=lambda values: values[0])


def build_trajectory_panel(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    descriptor_names = list(adapter.DESCRIPTOR_COLUMNS)
    rows: list[pd.DataFrame] = []
    neighbor_rows: list[pd.DataFrame] = []
    for (view, denominator), group in daily.groupby(
        ["market_view", "denominator"], sort=True
    ):
        group = group.sort_values("trade_date").reset_index(drop=True)
        if len(group) != 1457 or not group.hard_valid.astype(bool).all():
            raise MarketMinuteAnalysisError(f"daily group invalid: {view}:{denominator}")
        output = pd.DataFrame(
            {
                "trade_date": group.trade_date.iloc[4:].to_numpy(),
                "available_at": group.available_at.iloc[4:].to_numpy(),
                "market_view": view,
                "denominator": denominator,
                "daily_population_count": group.daily_population_count.iloc[4:].to_numpy(),
                "descriptor_count": group.descriptor_count.iloc[4:].to_numpy(),
                "descriptor_coverage": group.descriptor_coverage.iloc[4:].to_numpy(),
                "hard_valid": True,
                "cy6_snapshot_sha256": group.cy6_snapshot_sha256.iloc[4:].to_numpy(),
                "cy8_snapshot_selection_sha256": group.cy8_snapshot_selection_sha256.iloc[4:].to_numpy(),
            }
        )
        neighbor = output[["trade_date", "market_view", "denominator"]].copy()
        percentile_arrays: dict[str, dict[str, np.ndarray]] = {}
        for label in ("p40", "median", "p60"):
            values = group[[f"{name}__{label}" for name in descriptor_names]].to_numpy(float)
            if not np.isfinite(values).all():
                raise MarketMinuteAnalysisError(f"nonfinite daily descriptor: {view}:{denominator}:{label}")
            percentile_arrays[label] = trajectory_arrays(values)
        for descriptor_index, name in enumerate(descriptor_names):
            for shape, values in percentile_arrays["median"].items():
                output[f"{name}__{shape}"] = values[:, descriptor_index]
            for label in ("p40", "p60"):
                neighbor[f"{name}__ols_slope5__{label}"] = percentile_arrays[label][
                    "ols_slope5"
                ][:, descriptor_index]
        rows.append(output)
        neighbor_rows.append(neighbor)
    trajectory = pd.concat(rows, ignore_index=True).sort_values(
        ["trade_date", "market_view", "denominator"]
    ).reset_index(drop=True)
    neighbors = pd.concat(neighbor_rows, ignore_index=True).sort_values(
        ["trade_date", "market_view", "denominator"]
    ).reset_index(drop=True)
    if len(trajectory) != 11624 or trajectory.duplicated(
        ["trade_date", "market_view", "denominator"]
    ).any():
        raise MarketMinuteAnalysisError("trajectory population changed")
    return trajectory, neighbors


def add_pit_and_relative_coordinates(trajectory: pd.DataFrame) -> pd.DataFrame:
    output = trajectory.copy()
    descriptor_names = list(adapter.DESCRIPTOR_COLUMNS)
    for (_, _), index in output.groupby(["market_view", "denominator"], sort=True).groups.items():
        ordered_index = output.loc[index].sort_values("trade_date").index
        for name in descriptor_names:
            primary = f"{name}__ols_slope5"
            series = output.loc[ordered_index, primary]
            output.loc[ordered_index, f"{primary}__pit_expanding_pct"] = causal_expanding_percentile(series).to_numpy()
            output.loc[ordered_index, f"{primary}__pit_3y_pct"] = causal_rolling_percentile(series).to_numpy()
            output.loc[ordered_index, f"{primary}__pit_3y_robust_z"] = causal_rolling_robust_z(series).to_numpy()
    for name in descriptor_names:
        primary = f"{name}__ols_slope5"
        relative_column = f"{primary}__relative_to_all_a"
        rank_column = f"{primary}__view_rank"
        output[relative_column] = np.nan
        output[rank_column] = np.nan
        for (_, _), index in output.groupby(["trade_date", "denominator"], sort=True).groups.items():
            cell = output.loc[index]
            all_a = cell.loc[cell.market_view.eq("ALL_A"), primary]
            if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
                continue
            output.loc[index, relative_column] = cell[primary] - float(all_a.iloc[0])
            output.loc[index, rank_column] = cell[primary].rank(method="average", pct=True)
    return output


def representation_diagnostics(
    daily: pd.DataFrame, trajectory: pd.DataFrame, neighbors: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame]:
    descriptor_names = list(adapter.DESCRIPTOR_COLUMNS)
    gates = spec["representation_gates"]
    decisions: dict[str, Any] = {}
    for name in descriptor_names:
        level_neighbor_values: list[float] = []
        trajectory_aggregation_values: list[float] = []
        trajectory_shape_values: list[float] = []
        year_cells_valid = True
        for (view, denominator), group in daily.groupby(
            ["market_view", "denominator"], sort=True
        ):
            group = group.sort_values("trade_date")
            for label in ("p40", "p60"):
                level_neighbor_values.append(
                    _spearman(group[f"{name}__median"], group[f"{name}__{label}"])
                )
            tgroup = trajectory.loc[
                trajectory.market_view.eq(view) & trajectory.denominator.eq(denominator)
            ].sort_values("trade_date")
            ngroup = neighbors.loc[
                neighbors.market_view.eq(view) & neighbors.denominator.eq(denominator)
            ].sort_values("trade_date")
            for label in ("p40", "p60"):
                trajectory_aggregation_values.append(
                    _spearman(
                        tgroup[f"{name}__ols_slope5"],
                        ngroup[f"{name}__ols_slope5__{label}"],
                    )
                )
            trajectory_shape_values.extend(
                [
                    _spearman(
                        tgroup[f"{name}__ols_slope5"],
                        tgroup[f"{name}__endpoint_slope5"],
                    ),
                    _spearman(
                        tgroup[f"{name}__ols_slope5"],
                        tgroup[f"{name}__ols_slope3"],
                    ),
                ]
            )
            for _, year_group in tgroup.groupby(pd.to_datetime(tgroup.trade_date).dt.year):
                values = year_group[f"{name}__ols_slope5"]
                if len(values) < int(gates["view_year_minimum_observations"]) or values.nunique() < 2:
                    year_cells_valid = False
        denominator_values: list[float] = []
        for view in sorted(trajectory.market_view.unique()):
            cell = trajectory.loc[trajectory.market_view.eq(view)].pivot(
                index="trade_date", columns="denominator", values=f"{name}__ols_slope5"
            )
            denominator_values.append(_spearman(cell["ALL_STATUS"], cell["NON_ST"]))
        level_neighbor = float(np.nanmin(level_neighbor_values))
        trajectory_aggregation = float(np.nanmin(trajectory_aggregation_values))
        trajectory_shape = float(np.nanmin(trajectory_shape_values))
        denominator_stability = float(np.nanmedian(denominator_values))
        level_pass = (
            level_neighbor >= float(gates["worst_median_neighbor_spearman"])
            and denominator_stability >= float(gates["all_status_vs_non_st_median_spearman"])
            and year_cells_valid
        )
        trajectory_pass = (
            trajectory_aggregation >= float(gates["worst_median_neighbor_spearman"])
            and trajectory_shape >= float(gates["worst_median_neighbor_spearman"])
            and denominator_stability >= float(gates["all_status_vs_non_st_median_spearman"])
            and year_cells_valid
        )
        primary = trajectory[f"{name}__ols_slope5"]
        pit_column = trajectory[f"{name}__ols_slope5__pit_3y_pct"]
        post_warmup = trajectory.groupby(["market_view", "denominator"]).cumcount() >= 503
        decisions[name] = {
            "family": FAMILY_BY_DESCRIPTOR[name],
            "level_worst_cross_section_neighbor_spearman": level_neighbor,
            "trajectory_worst_cross_section_neighbor_spearman": trajectory_aggregation,
            "trajectory_worst_shape_neighbor_spearman": trajectory_shape,
            "all_status_vs_non_st_median_spearman": denominator_stability,
            "all_view_year_cells_nondegenerate": bool(year_cells_valid),
            "raw_coverage": float(primary.notna().mean()),
            "pit_post_warmup_coverage": float(pit_column.loc[post_warmup].notna().mean()),
            "relative_coverage": float(trajectory[f"{name}__ols_slope5__relative_to_all_a"].notna().mean()),
            "level_gate": "PASS" if level_pass else "FAIL",
            "trajectory_gate": "PASS" if trajectory_pass else "FAIL",
        }

    level_columns = {name: f"{name}__median" for name in descriptor_names}
    level_correlation = daily[list(level_columns.values())].rename(
        columns={value: key for key, value in level_columns.items()}
    ).corr(method="spearman")
    slope_columns = {name: f"{name}__ols_slope5" for name in descriptor_names}
    trajectory_correlation = trajectory[list(slope_columns.values())].rename(
        columns={value: key for key, value in slope_columns.items()}
    ).corr(method="spearman")

    def compress(correlation: pd.DataFrame, gate_name: str) -> tuple[list[str], dict[str, str]]:
        accepted: list[str] = []
        dispositions: dict[str, str] = {}
        for name in gates["minimal_panel_priority"]:
            if decisions[name][gate_name] != "PASS":
                dispositions[name] = f"{gate_name.lower()}_failed"
                continue
            redundant = [
                prior
                for prior in accepted
                if abs(float(correlation.loc[name, prior]))
                > float(gates["latent_component_edge_absolute_spearman"])
            ]
            if redundant:
                dispositions[name] = f"redundant_with:{redundant[0]}"
            else:
                accepted.append(name)
                dispositions[name] = "ACCEPT"
        return accepted, dispositions

    level_accepted, level_dispositions = compress(level_correlation, "level_gate")
    trajectory_accepted, trajectory_dispositions = compress(
        trajectory_correlation, "trajectory_gate"
    )
    compression = {
        "level_components": _components(
            level_correlation, float(gates["latent_component_edge_absolute_spearman"])
        ),
        "trajectory_components": _components(
            trajectory_correlation, float(gates["latent_component_edge_absolute_spearman"])
        ),
        "minimal_level_roles": level_accepted,
        "minimal_trajectory_roles": trajectory_accepted,
        "level_dispositions": level_dispositions,
        "trajectory_dispositions": trajectory_dispositions,
    }
    return decisions, compression, trajectory_correlation


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _report(result: dict[str, Any]) -> str:
    decisions = result["representations"]
    lines = [
        "# MKT-MIN-001 market intraday representation freeze",
        "",
        f"Decision: `{result['decision']}`.",
        "",
        "## Boundary",
        "",
        f"- Required raw rows: {result['required_scale']['raw_rows']:,}.",
        f"- Final causal security-sessions: {result['required_scale']['final_descriptor_sessions']:,}.",
        f"- Daily / five-day market rows: {result['population']['daily_rows']:,} / {result['population']['trajectory_rows']:,}.",
        "- Strategy membership, outcomes, future returns, post-entry paths, and CY-011 read: **none**.",
        "- This freezes representation quality only; it establishes no supply/demand mechanism, habitat, forecast, or strategy.",
        "",
        "## Representation gates",
        "",
        "| Descriptor | Family | Level neighbor | Trajectory aggregation | Trajectory shape | ST sensitivity | Level | Trajectory | Level minimal | Trajectory minimal |",
        "|---|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for name in adapter.DESCRIPTOR_COLUMNS:
        item = decisions[name]
        lines.append(
            f"| {name} | {item['family']} | {item['level_worst_cross_section_neighbor_spearman']:.3f} | "
            f"{item['trajectory_worst_cross_section_neighbor_spearman']:.3f} | "
            f"{item['trajectory_worst_shape_neighbor_spearman']:.3f} | "
            f"{item['all_status_vs_non_st_median_spearman']:.3f} | "
            f"{item['level_gate']} | {item['trajectory_gate']} | "
            f"{result['minimal_level_dispositions'][name]} | "
            f"{result['minimal_trajectory_dispositions'][name]} |"
        )
    lines.extend(
        [
            "",
            "## Outcome-blind compression",
            "",
            f"Minimal nonredundant same-session level roles: `{', '.join(result['minimal_nonredundant_level_roles']) or 'NONE'}`.",
            "",
            f"Minimal nonredundant five-day trajectory roles: `{', '.join(result['minimal_nonredundant_trajectory_roles']) or 'NONE'}`.",
            "",
            f"Same-session level absolute-Spearman components at 0.85: `{result['level_latent_components']}`.",
            "",
            f"Five-day trajectory absolute-Spearman components at 0.85: `{result['trajectory_latent_components']}`.",
            "",
            "Components diagnose redundant manifestations only. They do not prove latent causal mechanisms. Failed exact trajectories remain representation failures; their broader economic families remain open.",
            "",
            "## PIT and portability",
            "",
            f"Every group has {result['population']['trajectories_per_view_denominator']} five-day observations. Causal expanding/trailing percentiles and robust z-scores begin only at observation 504; post-warm-up percentile coverage is {result['pit']['minimum_post_warmup_percentile_coverage']:.3f}. Absolute p40/median/p60 values remain primary, with separate view-minus-ALL_A and view-rank coordinates.",
            "",
            "## Unavailable concepts",
            "",
            "Objective cross-day support/resistance defense and breakout-line acceptance remain unavailable because no action-safe cross-day raw minute level is registered. OHLCV cannot identify aggressor side, absorption, queues, hidden liquidity, or participants.",
            "",
            "## Reproducibility",
            "",
            f"- Daily input SHA-256: `{result['hashes']['daily_panel_sha256']}`.",
            f"- Trajectory panel SHA-256: `{result['hashes']['trajectory_panel_sha256']}`.",
            f"- Analysis spec SHA-256: `{result['hashes']['analysis_spec_sha256']}`.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = adapter.load_frozen_spec()
    bound = spec["required_scale_input"]
    if adapter._resolve(bound["path"]) != DAILY_PATH or sha256_file(DAILY_PATH) != bound["sha256"]:
        raise MarketMinuteAnalysisError("required daily panel identity mismatch")
    daily = pd.read_csv(DAILY_PATH)
    daily["trade_date"] = pd.to_datetime(daily.trade_date, errors="raise")
    if len(daily) != int(bound["daily_rows"]) or not daily.hard_valid.astype(bool).all():
        raise MarketMinuteAnalysisError("required daily panel gate failed")
    trajectory, neighbors = build_trajectory_panel(daily)
    trajectory = add_pit_and_relative_coordinates(trajectory)
    decisions, compression, correlation = representation_diagnostics(
        daily, trajectory, neighbors, spec
    )
    TRAJECTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    trajectory.to_parquet(
        TRAJECTORY_PATH, index=False, compression="zstd", engine="pyarrow"
    )
    if TRAJECTORY_PATH.stat().st_size + DAILY_PATH.stat().st_size > 100 * 1024**2:
        raise MarketMinuteAnalysisError("durable panels exceed frozen 100 MiB budget")

    absolute_summary: dict[str, Any] = {}
    for name in adapter.DESCRIPTOR_COLUMNS:
        level = daily[f"{name}__median"]
        slope = trajectory[f"{name}__ols_slope5"]
        absolute_summary[name] = {
            "level_minimum": float(level.min()),
            "level_median": float(level.median()),
            "level_maximum": float(level.max()),
            "trajectory_minimum": float(slope.min()),
            "trajectory_median": float(slope.median()),
            "trajectory_maximum": float(slope.max()),
        }
    result: dict[str, Any] = {
        "experiment_id": "MKT-MIN-001",
        "hypothesis_id": "MKT-H-007",
        "decision": "COMPLETE_LEVEL_REPRESENTATIONS_FROZEN_FIVE_DAY_TRAJECTORY_PRIMARIES_FAIL",
        "outcome_fields_read": [],
        "required_scale": bound,
        "population": {
            "daily_rows": int(len(daily)),
            "trajectory_rows": int(len(trajectory)),
            "trajectories_per_view_denominator": int(
                trajectory.groupby(["market_view", "denominator"]).size().min()
            ),
            "first_trajectory_date": trajectory.trade_date.min().date().isoformat(),
            "last_trajectory_date": trajectory.trade_date.max().date().isoformat(),
            "views": sorted(trajectory.market_view.unique().tolist()),
            "denominators": sorted(trajectory.denominator.unique().tolist()),
        },
        "representations": decisions,
        "minimal_nonredundant_level_roles": compression["minimal_level_roles"],
        "minimal_nonredundant_trajectory_roles": compression["minimal_trajectory_roles"],
        "minimal_level_dispositions": compression["level_dispositions"],
        "minimal_trajectory_dispositions": compression["trajectory_dispositions"],
        "level_latent_components": compression["level_components"],
        "trajectory_latent_components": compression["trajectory_components"],
        "absolute_summary": absolute_summary,
        "pit": {
            "minimum_history": int(spec["representation_gates"]["pit_minimum_observations"]),
            "minimum_post_warmup_percentile_coverage": float(
                min(item["pit_post_warmup_coverage"] for item in decisions.values())
            ),
            "normalization": "strictly causal including current completed observation only",
        },
        "limitations": {
            "economic_usefulness": "NOT_TESTED",
            "strategy_habitat": "NOT_TESTED",
            "mechanism_causality": "NOT_ESTABLISHED",
            "support_resistance": "UNAVAILABLE_NO_ACTION_SAFE_CROSS_DAY_MINUTE_LEVEL",
            "order_flow_identity": "UNAVAILABLE_FROM_OHLCV",
            "pit_grade": "bounded PIT-B",
        },
        "hashes": {
            "daily_panel_sha256": sha256_file(DAILY_PATH),
            "trajectory_panel_sha256": sha256_file(TRAJECTORY_PATH),
            "analysis_spec_sha256": sha256_file(SPEC_PATH),
            "adapter_sha256": sha256_file(ADAPTER_PATH),
        },
        "top_absolute_trajectory_spearman_pairs": sorted(
            [
                {
                    "left": left,
                    "right": right,
                    "rho": float(correlation.loc[left, right]),
                    "abs_rho": abs(float(correlation.loc[left, right])),
                }
                for index, left in enumerate(correlation.columns)
                for right in correlation.columns[index + 1 :]
            ],
            key=lambda item: (-item["abs_rho"], item["left"], item["right"]),
        )[:30],
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(
        json.dumps(
            {
                "decision": final["decision"],
                "population": final["population"],
                "minimal_nonredundant_level_roles": final["minimal_nonredundant_level_roles"],
                "minimal_nonredundant_trajectory_roles": final["minimal_nonredundant_trajectory_roles"],
                "hashes": final["hashes"],
            },
            indent=2,
            sort_keys=True,
        )
    )
