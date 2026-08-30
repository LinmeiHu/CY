#!/usr/bin/env python3
"""Build full-market objective-breakout formation representations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
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

SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DIFF-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-001_panel.csv"
STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-001_stability_audit.csv"
EXTERNAL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-001_external_geometry_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DIFF-001_representation.md"
EXPECTED_SPEC_SHA256 = "9a7d63ebbab4d23e9fee955748c23b1112aa370aa725e1eb24c83f998dd0aa27"

DATA_RUNNER_PATH = PROGRAM / "scripts/run_mkt_breakout_diff_data_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_breakout_diff_data_001_parent", DATA_RUNNER_PATH
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load frozen breakout-diffusion data runner")
data_runner = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(data_runner)


class BreakoutDiffusionRepresentationError(RuntimeError):
    """Fail-closed full-market breakout-diffusion representation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise BreakoutDiffusionRepresentationError("representation spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_FULL_MARKET_LEVEL_REPRESENTATION_ESTIMATES"
        or spec["outcome_access"] is not False
    ):
        raise BreakoutDiffusionRepresentationError("representation activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise BreakoutDiffusionRepresentationError(f"input identity mismatch: {name}")

    data_result = json.loads(_resolve(spec["inputs"]["data_result"]["path"]).read_text())
    failed = sorted(
        key
        for key, value in data_result["gate_evaluation"]["coverage"].items()
        if not value["pass"]
    )
    if (
        data_result["status"] != spec["data_activation"]["required_status"]
        or failed != ["L40:CHINEXT_BOARD:ALL_STATUS", "L40:CHINEXT_BOARD:NON_ST"]
        or not data_result["gate_evaluation"]["annual_primary_pass"]
        or not data_result["protected_coordinate_replication"]["exact_match"]
        or data_result["cy011_read"]
    ):
        raise BreakoutDiffusionRepresentationError("data-domain activation changed")
    breadth = json.loads(_resolve(spec["inputs"]["breadth_result"]["path"]).read_text())
    if breadth["minimal_panel"]["accepted_roles"] != [
        "new_high_low",
        "leadership_concentration",
    ]:
        raise BreakoutDiffusionRepresentationError("external breadth controls changed")
    if sorted(spec["data_activation"]["failed_roles_not_advanced"]) != [
        "acceptance_diffusion",
        "acceptance_leadership_concentration",
    ]:
        raise BreakoutDiffusionRepresentationError("failed-role boundary changed")
    return spec


def _role_columns(spec: dict[str, Any]) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        role: (definition["primary"], tuple(definition["neighbors"]))
        for role, definition in spec["roles"].items()
    }


def _daily_representations(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> pd.DataFrame:
    data_runner._expanded_view(connection)
    frames: list[pd.DataFrame] = []
    for raw_horizon in spec["population"]["lookbacks"]:
        horizon = int(raw_horizon)
        frame = connection.execute(
            f"""
            WITH overall AS (
              SELECT market_view,denominator,trade_date,
                     count(*) AS eligible_count,
                     count(causal_industry) AS industry_mapped_count,
                     sum(cross{horizon}::INTEGER) AS crossing_count,
                     sum(above{horizon}::INTEGER) AS close_above_count,
                     sum(equal{horizon}::INTEGER) AS close_equal_count,
                     sum(below{horizon}::INTEGER) AS close_below_count,
                     avg(formation_depth{horizon}) FILTER (WHERE cross{horizon})
                       AS formation_depth,
                     avg(rejection_depth{horizon}) FILTER (WHERE cross{horizon})
                       AS rejection_depth
              FROM expanded GROUP BY 1,2,3
            ), industries AS (
              SELECT market_view,denominator,trade_date,causal_industry,
                     count(*) AS industry_eligible_count,
                     sum(cross{horizon}::INTEGER) AS industry_crossing_count
              FROM expanded WHERE causal_industry IS NOT NULL
              GROUP BY 1,2,3,4 HAVING count(*)>=5
            ), industry_context AS (
              SELECT *,sum(industry_eligible_count) OVER w AS included_eligible_count,
                     sum(industry_crossing_count) OVER w AS included_crossing_count
              FROM industries
              WINDOW w AS (PARTITION BY market_view,denominator,trade_date)
            ), industry_scored AS (
              SELECT *,greatest(
                       industry_crossing_count
                       - included_crossing_count::DOUBLE
                         /nullif(included_eligible_count,0)*industry_eligible_count,
                       0.0) AS positive_excess
              FROM industry_context
            ), industry_ranked AS (
              SELECT *,row_number() OVER (
                       PARTITION BY market_view,denominator,trade_date
                       ORDER BY positive_excess DESC,causal_industry) AS excess_rank
              FROM industry_scored
            ), industry_daily AS (
              SELECT market_view,denominator,trade_date,
                     count(*) AS included_industry_count,
                     max(included_eligible_count) AS included_eligible_count,
                     max(included_crossing_count) AS included_crossing_count,
                     sum((industry_crossing_count>0)::INTEGER) AS event_industry_count,
                     avg(industry_crossing_count::DOUBLE/industry_eligible_count)
                       AS equal_industry_formation,
                     1.0-0.5*sum(abs(
                       industry_crossing_count::DOUBLE/nullif(included_crossing_count,0)
                       -industry_eligible_count::DOUBLE/included_eligible_count))
                       AS formation_diffusion,
                     sum(CASE WHEN excess_rank<=1 THEN positive_excess ELSE 0 END)
                       /nullif(sum(positive_excess),0) AS leadership_top1,
                     sum(CASE WHEN excess_rank<=3 THEN positive_excess ELSE 0 END)
                       /nullif(sum(positive_excess),0) AS leadership_top3,
                     sum(CASE WHEN excess_rank<=5 THEN positive_excess ELSE 0 END)
                       /nullif(sum(positive_excess),0) AS leadership_top5
              FROM industry_ranked GROUP BY 1,2,3
            )
            SELECT o.*,i.included_industry_count,i.included_eligible_count,
                   i.included_crossing_count,i.event_industry_count,
                   i.equal_industry_formation,i.formation_diffusion,
                   i.leadership_top1,i.leadership_top3,i.leadership_top5
            FROM overall o LEFT JOIN industry_daily i
              USING(market_view,denominator,trade_date)
            ORDER BY trade_date,denominator,market_view
            """
        ).df()
        frame["lookback"] = horizon
        frames.append(frame)
    long = pd.concat(frames, ignore_index=True)
    long["trade_date"] = pd.to_datetime(long["trade_date"], errors="raise")
    minimums = data_runner._load_spec()["population"]["minimum_counts"]
    long["view_valid"] = long["eligible_count"] >= long["market_view"].map(minimums)
    long["industry_mapping_coverage"] = long["industry_mapped_count"] / long["eligible_count"]
    data_spec = data_runner._load_spec()["population"]
    long["formation_domain"] = (
        long["view_valid"]
        & long["industry_mapping_coverage"].ge(data_spec["industry_mapping_minimum"])
        & long["included_industry_count"].ge(data_spec["industry_count_minimum"])
        & long["event_industry_count"].ge(data_spec["formation_event_industry_minimum"])
    )

    value_columns = [
        "formation_depth",
        "rejection_depth",
        "equal_industry_formation",
        "formation_diffusion",
        "leadership_top1",
        "leadership_top3",
        "leadership_top5",
    ]
    counts = [
        "eligible_count",
        "industry_mapped_count",
        "crossing_count",
        "close_above_count",
        "close_equal_count",
        "close_below_count",
        "included_industry_count",
        "included_eligible_count",
        "included_crossing_count",
        "event_industry_count",
    ]
    index = ["trade_date", "market_view", "denominator"]
    pieces: list[pd.DataFrame] = []
    for horizon, group in long.groupby("lookback", sort=True):
        cell = group[index + counts + ["view_valid", "formation_domain"] + value_columns].copy()
        rename = {
            column: f"{column}{int(horizon)}"
            for column in [*counts, "formation_domain", *value_columns]
        }
        cell = cell.rename(columns=rename)
        if int(horizon) != 20:
            cell = cell.drop(columns="view_valid")
        pieces.append(cell)
    wide = pieces[0]
    for piece in pieces[1:]:
        wide = wide.merge(piece, on=index, validate="one_to_one")

    for horizon in (10, 20, 40):
        crossing = wide[f"crossing_count{horizon}"].astype(float)
        eligible = wide[f"eligible_count{horizon}"].astype(float)
        wide[f"breakout_formation_participation{horizon}"] = crossing / eligible
        wide[f"breakout_formation_depth{horizon}"] = wide[f"formation_depth{horizon}"]
        wide[f"breakout_closing_acceptance{horizon}"] = (
            wide[f"close_above_count{horizon}"] / crossing
        )
        wide[f"breakout_closing_rejection_depth{horizon}"] = wide[f"rejection_depth{horizon}"]
        wide[f"breakout_equal_industry_formation{horizon}"] = wide[
            f"equal_industry_formation{horizon}"
        ].where(wide[f"formation_domain{horizon}"])
        wide[f"breakout_formation_diffusion{horizon}"] = wide[
            f"formation_diffusion{horizon}"
        ].where(wide[f"formation_domain{horizon}"])
        for top in (1, 3, 5):
            wide[f"breakout_formation_leadership_top{top}_{horizon}"] = wide[
                f"leadership_top{top}{horizon}"
            ].where(wide[f"formation_domain{horizon}"])
        wide[f"breakout_stock_industry_divergence{horizon}"] = (
            wide[f"breakout_formation_participation{horizon}"]
            - wide[f"breakout_equal_industry_formation{horizon}"]
        )
    expected = spec["population"]
    if (
        len(wide) != expected["expected_date_view_denominator_rows"]
        or wide["trade_date"].nunique() != expected["expected_post_warmup_dates"]
    ):
        raise BreakoutDiffusionRepresentationError("daily representation population changed")
    primary = wide.loc[wide["market_view"].eq("ALL_A") & wide["denominator"].eq("ALL_STATUS")]
    if (
        int(primary["eligible_count20"].sum())
        != expected["expected_eligible_all_a_all_status_security_dates"]
    ):
        raise BreakoutDiffusionRepresentationError("eligible security-date population changed")
    states = wide["close_above_count20"] + wide["close_equal_count20"] + wide["close_below_count20"]
    if not np.array_equal(states.to_numpy(), wide["crossing_count20"].to_numpy()):
        raise BreakoutDiffusionRepresentationError("closing-state conservation changed")
    return wide.sort_values(index).reset_index(drop=True)


def _attach_coordinates(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.copy().sort_values(["market_view", "denominator", "trade_date"])
    primaries = [definition["primary"] for definition in spec["roles"].values()]
    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for column in primaries:
            item[f"{column}_pit_expanding_pct"] = causal_expanding_percentile(item[column])
            item[f"{column}_pit_3y_pct"] = causal_rolling_percentile(item[column])
            item[f"{column}_pit_3y_robust_z"] = causal_rolling_robust_z(item[column])
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True)
    out = out.sort_values(["trade_date", "denominator", "market_view"])
    for column in primaries:
        all_values = out.loc[
            out["market_view"].eq("ALL_A"), ["trade_date", "denominator", column]
        ].rename(columns={column: "_all_value"})
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left")
        out[f"{column}_relative_to_all"] = out[column] - out["_all_value"]
        counts = out.groupby(["trade_date", "denominator"])[column].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[column].rank(method="average", pct=True)
        out[f"{column}_relative_view_rank_pct"] = ranks.where(counts >= 3)
        out = out.drop(columns="_all_value")
    out["decision_at"] = out["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    out["available_at"] = out["decision_at"]
    out["snapshot_id"] = "CY-006:de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    complete = frame[[target, *controls]].dropna()
    n = len(complete)
    p = len(controls)
    if n <= p + 1:
        return float("nan")
    ranked = complete.rank(method="average", pct=True)
    y = ranked[target].to_numpy(float)
    x = np.column_stack([np.ones(n), *(ranked[column].to_numpy(float) for column in controls)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    total = float(np.sum((y - np.mean(y)) ** 2))
    if total == 0:
        return float("nan")
    r2 = 1.0 - float(np.sum((y - fitted) ** 2)) / total
    return 1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)


def connected_components(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    remaining = set(str(item) for item in correlation.columns)
    output: list[list[str]] = []
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
                if other in remaining and abs(float(correlation.loc[current, other])) > threshold:
                    stack.append(other)
        output.append(sorted(component))
    return sorted(output)


def _semantic_bounds(role: str, values: pd.Series) -> bool:
    values = values.dropna()
    if values.empty or not np.isfinite(values.to_numpy(float)).all():
        return False
    if role in {
        "formation_participation",
        "closing_acceptance",
        "equal_industry_formation",
        "formation_diffusion",
        "formation_leadership_concentration",
    }:
        return bool(values.between(0, 1).all())
    if role in {"formation_depth", "closing_rejection_depth"}:
        return bool(values.ge(0).all())
    if role == "stock_industry_divergence":
        return bool(values.between(-1, 1).all())
    raise BreakoutDiffusionRepresentationError(f"unknown semantic-bound role: {role}")


def _stability_diagnostics(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    diagnostics: dict[str, Any] = {}
    audit_rows: list[dict[str, Any]] = []
    gates = spec["gates"]
    primary_panel = panel.loc[panel["denominator"].eq("ALL_STATUS")].copy()
    for role, definition in spec["roles"].items():
        primary = definition["primary"]
        neighbors = definition["neighbors"]
        domain = definition["domain"]
        coverage_by_view: dict[str, float] = {}
        for view, group in primary_panel.groupby("market_view", sort=True):
            coverage_by_view[str(view)] = float(group[primary].notna().mean())
        neighbor_stats: dict[str, Any] = {}
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_view = {
                str(view): float(group[[primary, neighbor]].corr(method="spearman").iloc[0, 1])
                for view, group in primary_panel.groupby("market_view", sort=True)
            }
            median = float(np.median(list(by_view.values())))
            neighbor_medians.append(median)
            neighbor_stats[neighbor] = {"median_across_views": median, "by_view": by_view}
            for view, value in by_view.items():
                audit_rows.append(
                    {
                        "audit_type": "neighbor_spearman",
                        "role": role,
                        "definition": neighbor,
                        "group": view,
                        "value": value,
                    }
                )
        denominator_by_view: dict[str, float] = {}
        for view in sorted(panel["market_view"].unique()):
            wide = panel.loc[
                panel["market_view"].eq(view), ["trade_date", "denominator", primary]
            ].pivot(index="trade_date", columns="denominator", values=primary)
            denominator_by_view[str(view)] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.median(list(denominator_by_view.values())))
        year_support: dict[str, Any] = {}
        year_cells_pass = True
        with_year = primary_panel.assign(year=primary_panel["trade_date"].dt.year)
        for (view, year), group in with_year.groupby(["market_view", "year"], sort=True):
            values = group[primary].dropna()
            passed = bool(
                len(values) >= gates["view_year_minimum_observations"]
                and np.isfinite(values.std(ddof=0))
                and values.std(ddof=0) > 0
            )
            year_cells_pass &= passed
            year_support[f"{view}:{year}"] = {
                "n": len(values),
                "nondegenerate": passed,
                "p10": float(values.quantile(0.1)) if len(values) else None,
                "median": float(values.median()) if len(values) else None,
                "p90": float(values.quantile(0.9)) if len(values) else None,
            }
        expected_pit = (
            panel.groupby(["market_view", "denominator"], sort=False)[primary].transform(
                lambda series: series.notna().cumsum()
            )
            >= 504
        )
        pit_coverage = float(panel.loc[expected_pit, f"{primary}_pit_3y_pct"].notna().mean())
        relative_expected = panel["market_view"].ne("ALL_A") & panel[primary].notna()
        relative_coverage = float(
            panel.loc[relative_expected, f"{primary}_relative_to_all"].notna().mean()
        )
        minimum_coverage = (
            gates["nonindustry_minimum_raw_coverage"]
            if domain == "nonindustry"
            else gates["formation_industry_minimum_raw_coverage"]
        )
        bounds_pass = _semantic_bounds(role, panel[primary])
        construction_pass = bool(
            min(coverage_by_view.values()) >= minimum_coverage
            and min(neighbor_medians) >= gates["worst_median_neighbor_spearman"]
            and denominator_median >= gates["all_status_vs_non_st_median_spearman"]
            and year_cells_pass
            and bounds_pass
            and pit_coverage >= gates["pit_expected_coverage"]
            and relative_coverage >= gates["relative_expected_coverage"]
        )
        diagnostics[role] = {
            "primary": primary,
            "domain": domain,
            "coverage_by_view": coverage_by_view,
            "minimum_raw_coverage": min(coverage_by_view.values()),
            "neighbors": neighbor_stats,
            "worst_neighbor_median_spearman": min(neighbor_medians),
            "all_status_vs_non_st_by_view": denominator_by_view,
            "all_status_vs_non_st_median": denominator_median,
            "year_support": year_support,
            "all_view_year_cells_pass": bool(year_cells_pass),
            "semantic_bounds_pass": bounds_pass,
            "pit_expected_coverage": pit_coverage,
            "relative_expected_coverage": relative_coverage,
            "construction_gate_pass": construction_pass,
        }
        for metric, value in (
            ("minimum_raw_coverage", min(coverage_by_view.values())),
            ("worst_neighbor_median_spearman", min(neighbor_medians)),
            ("denominator_median_spearman", denominator_median),
            ("pit_expected_coverage", pit_coverage),
            ("relative_expected_coverage", relative_coverage),
            ("construction_gate_pass", float(construction_pass)),
        ):
            audit_rows.append(
                {
                    "audit_type": metric,
                    "role": role,
                    "definition": primary,
                    "group": "ALL",
                    "value": value,
                }
            )
    return diagnostics, pd.DataFrame(audit_rows)


def _external_geometry(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame]:
    breadth = pd.read_csv(_resolve(spec["inputs"]["breadth_panel"]["path"]))
    breadth["trade_date"] = pd.to_datetime(breadth["trade_date"], errors="raise")
    controls = spec["external_controls"]
    merged = panel.merge(
        breadth,
        on=["trade_date", "market_view", "denominator"],
        suffixes=("", "_breadth"),
        validate="one_to_one",
    )
    if merged.empty:
        raise BreakoutDiffusionRepresentationError("external breadth join is empty")
    control_raw = [controls["discovery"], controls["leadership_concentration"]]
    coordinate_suffixes = {
        "absolute": "",
        "pit_3y_pct": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
    }
    rows: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    for role, definition in spec["roles"].items():
        primary = definition["primary"]
        role_rows: list[dict[str, Any]] = []
        for coordinate, suffix in coordinate_suffixes.items():
            views = (
                controls["relative_views"]
                if coordinate == "relative_to_all"
                else controls["absolute_and_pit_views"]
            )
            target = f"{primary}{suffix}"
            control_columns = [f"{column}{suffix}" for column in control_raw]
            for denominator in controls["denominators"]:
                for view in views:
                    cell = merged.loc[
                        merged["denominator"].eq(denominator) & merged["market_view"].eq(view)
                    ]
                    complete = cell[[target, *control_columns]].dropna()
                    n = len(complete)
                    rhos = [
                        float(complete[[target, column]].corr(method="spearman").iloc[0, 1])
                        if n > 1
                        else float("nan")
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
                        "role": role,
                        "coordinate": coordinate,
                        "market_view": view,
                        "denominator": denominator,
                        "n": n,
                        "rho_discovery": rhos[0],
                        "rho_leadership_concentration": rhos[1],
                        "joint_adjusted_rank_r2": joint,
                        "gate_pass": passed,
                    }
                    rows.append(record)
                    role_rows.append(record)
        result[role] = {
            "cells": len(role_rows),
            "minimum_n": min(row["n"] for row in role_rows),
            "maximum_absolute_pairwise_spearman": max(
                max(abs(row["rho_discovery"]), abs(row["rho_leadership_concentration"]))
                for row in role_rows
            ),
            "maximum_joint_adjusted_rank_r2": max(
                row["joint_adjusted_rank_r2"] for row in role_rows
            ),
            "all_external_cells_pass": all(row["gate_pass"] for row in role_rows),
        }
    return result, pd.DataFrame(rows)


def _scalar_aggregate_cases(
    connection: duckdb.DuckDBPyConnection, panel: pd.DataFrame
) -> list[dict[str, Any]]:
    candidates = panel.loc[
        panel["formation_domain20"].astype(bool) & panel["breakout_formation_depth20"].notna()
    ].copy()
    candidates["selection_hash"] = candidates.apply(
        lambda row: hashlib.sha256(
            (
                f"MKT-BREAKOUT-DIFF-001|{row.trade_date.date()}|{row.market_view}|{row.denominator}"
            ).encode()
        ).hexdigest(),
        axis=1,
    )
    selected = candidates.sort_values("selection_hash").head(5)
    if len(selected) != 5:
        raise BreakoutDiffusionRepresentationError("insufficient aggregate scalar cases")
    output: list[dict[str, Any]] = []
    for row in selected.itertuples(index=False):
        filters = {
            "ALL_A": "symbol LIKE '%.SH' OR symbol LIKE '%.SZ'",
            "SH_A": "symbol LIKE '%.SH'",
            "SZ_A": "symbol LIKE '%.SZ'",
            "CHINEXT_BOARD": (
                "symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')"
            ),
        }
        status_filter = "" if row.denominator == "ALL_STATUS" else " AND is_st IS FALSE"
        scalar = connection.execute(
            f"""
            SELECT count(*) AS eligible_count,sum(cross20::INTEGER) AS crossing_count,
                   sum(above20::INTEGER) AS close_above_count,
                   sum(equal20::INTEGER) AS close_equal_count,
                   sum(below20::INTEGER) AS close_below_count
            FROM event_security WHERE trade_date=? AND ({filters[row.market_view]})
              {status_filter}
            """,
            [pd.Timestamp(row.trade_date)],
        ).fetchone()
        exact = (
            int(scalar[0]) == int(row.eligible_count20),
            int(scalar[1]) == int(row.crossing_count20),
            int(scalar[2]) == int(row.close_above_count20),
            int(scalar[3]) == int(row.close_equal_count20),
            int(scalar[4]) == int(row.close_below_count20),
            float(scalar[1] / scalar[0]) == float(row.breakout_formation_participation20),
            float(scalar[2] / scalar[1]) == float(row.breakout_closing_acceptance20),
        )
        if not all(exact):
            raise BreakoutDiffusionRepresentationError(
                f"aggregate scalar disagreement: {row.trade_date}:{row.market_view}:"
                f"{row.denominator}:{exact}"
            )
        output.append(
            {
                "selection_hash": row.selection_hash,
                "trade_date": str(pd.Timestamp(row.trade_date).date()),
                "market_view": str(row.market_view),
                "denominator": str(row.denominator),
                "eligible_count": int(scalar[0]),
                "crossing_count": int(scalar[1]),
                "close_above_count": int(scalar[2]),
                "close_equal_count": int(scalar[3]),
                "close_below_count": int(scalar[4]),
                "exact_match": True,
            }
        )
    return output


def _correlation_dict(correlation: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        str(row): {
            str(column): float(correlation.loc[row, column]) for column in correlation.columns
        }
        for row in correlation.index
    }


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    population = result["population"]
    construction = ", ".join(result["construction_pass_roles"]) or "NONE"
    external_roles = ", ".join(result["externally_distinct_roles"]) or "NONE"
    direct_roles = ", ".join(result["minimal_panel"]["accepted_roles"]) or "NONE"
    lines = [
        "# MKT-BREAKOUT-DIFF-001 full-market representation",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Daily rows: {population['rows']:,}; eligible ALL_A/ALL_STATUS "
        f"security-dates: {population['eligible_security_dates']:,}.",
        "- Failed L40 ChiNext acceptance-industry roles remain unestimated and excluded.",
        f"- Construction-pass roles: `{construction}`.",
        f"- Externally distinct roles: `{external_roles}`.",
        f"- Final minimal direct roles: `{direct_roles}`.",
        "- This is representation/geometry evidence only; no transition, outcome, "
        "habitat, timing, execution, or strategy claim is permitted.",
        "",
        "## Fixed role gates",
        "",
        "| Role | Min coverage | Worst neighbor rho | ST rho | PIT coverage | "
        "Relative coverage | Construction | External | Final |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in spec["gates"]["minimal_role_priority"]:
        item = result["role_diagnostics"][role]
        external = result["external_geometry"][role]
        final_disposition = (
            "RETAIN"
            if role in accepted
            else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        )
        lines.append(
            f"| {role} | {item['minimum_raw_coverage']:.3f} | "
            f"{item['worst_neighbor_median_spearman']:.3f} | "
            f"{item['all_status_vs_non_st_median']:.3f} | "
            f"{item['pit_expected_coverage']:.3f} | "
            f"{item['relative_expected_coverage']:.3f} | "
            f"{'PASS' if item['construction_gate_pass'] else 'FAIL'} | "
            f"{'PASS' if external['all_external_cells_pass'] else 'FAIL'} | "
            f"{final_disposition} |"
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
            f"- External geometry SHA-256: `{result['hashes']['external_geometry_audit_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    data_spec = data_runner._load_spec()
    paths, source_hashes = data_runner._verify_registry_and_partitions(data_spec)
    data_runner._preflight_resource_guard(data_spec, paths)
    with tempfile.TemporaryDirectory(prefix="mkt_breakout_diff_001_") as temporary:
        temp_dir = Path(temporary)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1.5GB'")
        connection.execute("SET temp_directory=?", [str(temp_dir / "spill")])
        try:
            input_audit = data_runner._create_source_and_audit(connection, paths, data_spec)
            data_runner._create_event_security(connection)
            data_runner._phase_resource_guard(data_spec, temp_dir, started)
            raw_panel = _daily_representations(connection, spec)
            panel = _attach_coordinates(raw_panel, spec)
            scalar_cases = _scalar_aggregate_cases(connection, panel)
            data_runner._phase_resource_guard(data_spec, temp_dir, started)
        finally:
            connection.close()

    diagnostics, stability_audit = _stability_diagnostics(panel, spec)
    external, external_audit = _external_geometry(panel, spec)
    role_columns = _role_columns(spec)
    construction_pass = [
        role
        for role in spec["gates"]["minimal_role_priority"]
        if diagnostics[role]["construction_gate_pass"]
    ]
    externally_distinct = [
        role for role in construction_pass if external[role]["all_external_cells_pass"]
    ]
    primary_columns = {role: role_columns[role][0] for role in spec["roles"]}
    correlation_source = panel.loc[
        panel["market_view"].eq("ALL_A") & panel["denominator"].eq("ALL_STATUS"),
        [primary_columns[role] for role in spec["gates"]["minimal_role_priority"]],
    ].rename(columns={value: key for key, value in primary_columns.items()})
    correlation = correlation_source.corr(method="spearman")
    threshold = spec["gates"]["internal_redundancy_absolute_spearman"]
    components = connected_components(correlation, threshold)
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in spec["gates"]["minimal_role_priority"]:
        if role not in construction_pass:
            excluded[role] = "construction_gate_failed"
            continue
        if role not in externally_distinct:
            excluded[role] = "externally_reconstructable"
            continue
        blockers = [
            other for other in accepted if abs(float(correlation.loc[role, other])) > threshold
        ]
        if blockers:
            excluded[role] = "internally_redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)

    role_columns_output = [
        column for definition in role_columns.values() for column in (definition[0], *definition[1])
    ]
    primaries = [definition[0] for definition in role_columns.values()]
    coordinate_columns = [
        f"{primary}{suffix}"
        for primary in primaries
        for suffix in (
            "_pit_expanding_pct",
            "_pit_3y_pct",
            "_pit_3y_robust_z",
            "_relative_to_all",
            "_relative_view_rank_pct",
        )
    ]
    audit_columns = [
        "trade_date",
        "market_view",
        "denominator",
        "eligible_count20",
        "crossing_count20",
        "close_above_count20",
        "close_equal_count20",
        "close_below_count20",
        "industry_mapped_count20",
        "included_industry_count20",
        "event_industry_count20",
        "formation_domain10",
        "formation_domain20",
        "formation_domain40",
        "decision_at",
        "available_at",
        "snapshot_id",
    ]
    output = panel[audit_columns + role_columns_output + coordinate_columns].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    stability_audit.to_csv(STABILITY_PATH, index=False, float_format="%.17g", lineterminator="\n")
    external_audit.to_csv(EXTERNAL_PATH, index=False, float_format="%.17g", lineterminator="\n")

    status = (
        "COMPLETE_SUPPORTED_LEVEL_REPRESENTATION_GEOMETRY"
        if accepted
        else "COMPLETE_NO_DIRECT_LEVEL_REPRESENTATION"
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": "REPRESENTATION_AND_EXTERNAL_GEOMETRY_ONLY",
        "failed_acceptance_industry_roles_estimated": False,
        "outcome_or_strategy_fields_read": [],
        "qd004_read": False,
        "cy008_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "input_audit": input_audit,
        "population": {
            "rows": len(output),
            "dates": int(panel["trade_date"].nunique()),
            "eligible_security_dates": int(
                panel.loc[
                    panel["market_view"].eq("ALL_A") & panel["denominator"].eq("ALL_STATUS"),
                    "eligible_count20",
                ].sum()
            ),
        },
        "role_diagnostics": diagnostics,
        "construction_pass_roles": construction_pass,
        "external_geometry": external,
        "externally_distinct_roles": externally_distinct,
        "internal_primary_spearman_all_a": _correlation_dict(correlation),
        "internal_latent_components": components,
        "minimal_panel": {
            "priority": spec["gates"]["minimal_role_priority"],
            "accepted_roles": accepted,
            "excluded_roles": excluded,
        },
        "scalar_reconstruction": scalar_cases,
        "resource_contract": {
            "status": "PASS",
            "dynamic_measurements_serialized": False,
            "memory_limit_gib": 1.5,
            "peak_rss_ceiling_gib": 3,
            "temporary_spill_ceiling_gib": 10,
            "wall_clock_ceiling_minutes": 10,
        },
        "unresolved": {
            "temporal_process": "NOT_TESTED",
            "economic_usefulness": "NOT_TESTED",
            "strategy_habitat": "NOT_TESTED",
            "strategy_archetype": "NONE",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "source_partitions": source_hashes,
            "panel_sha256": sha256_file(PANEL_PATH),
            "stability_audit_sha256": sha256_file(STABILITY_PATH),
            "external_geometry_audit_sha256": sha256_file(EXTERNAL_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result, spec), encoding="utf-8")
    durable_bytes = sum(
        path.stat().st_size
        for path in (PANEL_PATH, STABILITY_PATH, EXTERNAL_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable_bytes > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise BreakoutDiffusionRepresentationError("durable output ceiling breached")
    wall_ceiling = float(spec["resource_budget"]["wall_clock_ceiling_minutes"]) * 60
    if time.monotonic() - started > wall_ceiling:
        raise BreakoutDiffusionRepresentationError("wall-clock ceiling breached")
    print(
        json.dumps(
            {
                "status": status,
                "construction_pass_roles": construction_pass,
                "externally_distinct_roles": externally_distinct,
                "accepted_roles": accepted,
                "durable_output_bytes": durable_bytes,
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_bytes": data_runner._peak_rss_bytes(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result


if __name__ == "__main__":
    run()
