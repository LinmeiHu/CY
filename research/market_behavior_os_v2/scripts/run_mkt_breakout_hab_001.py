#!/usr/bin/env python3
"""Execute frozen prior-day market-state conditioning of breakout paths."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-HAB-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-HAB-001_state_response_panel.csv"
EDGE_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-HAB-001_edge_audit.csv"
JOINT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-HAB-001_joint_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-HAB-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-HAB-001_geometry.md"
EXPECTED_SPEC_SHA256 = "066ed2e8397fe766e726da9999ab5c22d5bc6c548134e92343633a2d010348f1"


class BreakoutHabitatError(RuntimeError):
    """Fail-closed MKT-BREAKOUT-HAB-001 error."""


def _sha256_file(path: Path) -> str:
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
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise BreakoutHabitatError("state-conditioning spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_PRIOR_STATE_JOIN_OR_ASSOCIATION_ESTIMATES":
        raise BreakoutHabitatError("state-conditioning activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or _sha256_file(path) != binding["sha256"]:
            raise BreakoutHabitatError(f"bound input identity mismatch: {name}")
    breakout = json.loads(_resolve(spec["inputs"]["breakout_result"]["path"]).read_text())
    trend = json.loads(_resolve(spec["inputs"]["trend_result"]["path"]).read_text())
    breadth = json.loads(_resolve(spec["inputs"]["breadth_result"]["path"]).read_text())
    geometry = json.loads(_resolve(spec["inputs"]["state_geometry_result"]["path"]).read_text())
    if (
        breakout["status"] != "COMPLETE_REPRESENTATION_PASS"
        or breakout["representation_summary"]["minimal_roles"] != list(spec["roles"])
        or trend["minimal_panel"]["accepted_roles"] != ["direction"]
        or breadth["minimal_panel"]["accepted_roles"]
        != ["new_high_low", "leadership_concentration"]
        or geometry["status"] != "COMPLETE_OUTCOME_BLIND_STATE_GEOMETRY"
    ):
        raise BreakoutHabitatError("parent representation activation changed")
    return spec


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if time.monotonic() - started > budget["wall_seconds"]:
        raise BreakoutHabitatError("wall-clock ceiling breached")
    if psutil.Process().memory_info().rss > budget["peak_rss_bytes"]:
        raise BreakoutHabitatError("RSS ceiling breached")


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    mapped = series.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise BreakoutHabitatError("boolean field changed")
    return mapped.astype(bool)


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _rank_residual(values: pd.Series, controls: pd.DataFrame) -> np.ndarray:
    ranked_y = values.rank(method="average").to_numpy(dtype=float)
    if controls.shape[1] == 0:
        return ranked_y - ranked_y.mean()
    ranked_x = controls.rank(method="average")
    design = np.column_stack(
        [
            np.ones(len(ranked_x)),
            *(ranked_x[column].to_numpy(dtype=float) for column in ranked_x),
        ]
    )
    return ranked_y - design @ np.linalg.lstsq(design, ranked_y, rcond=None)[0]


def _partial_spearman(
    frame: pd.DataFrame, response: str, state: str, controls: list[str]
) -> tuple[int, float, int, int]:
    complete = frame[[response, state, *controls]].dropna()
    response_unique = int(complete[response].nunique())
    state_unique = int(complete[state].nunique())
    if len(complete) <= len(controls) + 2 or response_unique < 2 or state_unique < 2:
        return len(complete), np.nan, response_unique, state_unique
    left = _rank_residual(complete[response], complete[controls])
    right = _rank_residual(complete[state], complete[controls])
    if np.std(left) == 0 or np.std(right) == 0:
        rho = np.nan
    else:
        rho = float(np.corrcoef(left, right)[0, 1])
    return len(complete), rho, response_unique, state_unique


def _adjusted_rank_r2(frame: pd.DataFrame, response: str, controls: list[str]) -> float:
    complete = frame[[response, *controls]].dropna()
    n = len(complete)
    p = len(controls)
    if n <= p + 1 or complete[response].nunique() < 2:
        return np.nan
    ranked = complete.rank(method="average")
    y = ranked[response].to_numpy(dtype=float)
    design = np.column_stack(
        [np.ones(n), *(ranked[column].to_numpy(dtype=float) for column in controls)]
    )
    fitted = design @ np.linalg.lstsq(design, y, rcond=None)[0]
    total = float(np.square(y - y.mean()).sum())
    if total == 0:
        return np.nan
    r2 = 1.0 - float(np.square(y - fitted).sum()) / total
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _parse_available(frame: pd.DataFrame, label: str) -> None:
    available = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    decision = pd.to_datetime(frame["decision_at"], utc=True, errors="raise")
    dates = pd.to_datetime(frame["trade_date"], errors="raise")
    local_dates = available.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None).dt.normalize()
    if not bool((available <= decision).all()) or not bool(
        local_dates.eq(dates.dt.normalize()).all()
    ):
        raise BreakoutHabitatError(f"{label} availability semantics changed")


def _load_inputs(
    spec: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    role_columns = set(spec["roles"])
    domain_columns = {item["domain_flag"] for item in spec["roles"].values()}
    control_columns = {control for item in spec["roles"].values() for control in item["controls"]}
    breakout_columns = {
        "audit_id",
        "sequence_id",
        "market_view",
        "symbol",
        "trade_date",
        "target_year",
        "definition",
        *role_columns,
        *domain_columns,
        *control_columns,
    }
    breakout = pd.read_csv(
        _resolve(spec["inputs"]["breakout_panel"]["path"]),
        usecols=sorted(breakout_columns),
        dtype={"symbol": str},
        float_precision="round_trip",
    )
    breakout["trade_date"] = pd.to_datetime(breakout["trade_date"], errors="raise")
    breakout = breakout.loc[
        breakout["definition"].eq(spec["population"]["breakout_definition"])
    ].copy()
    breakout["temporal_block"] = np.where(breakout["target_year"].le(2020), "A", "B")
    for flag in domain_columns:
        breakout[flag] = _as_bool(breakout[flag])
    if breakout["audit_id"].nunique() != len(breakout) or len(breakout) != 964:
        raise BreakoutHabitatError("primary breakout population changed")

    state_columns = spec["state_primitives"]
    trend_fields = {
        "trade_date",
        "index_symbol",
        "decision_at",
        "available_at",
        *(state_columns["A_direction"].values()),
    }
    trend = pd.read_csv(
        _resolve(spec["inputs"]["trend_panel"]["path"]),
        usecols=sorted(trend_fields),
        float_precision="round_trip",
    )
    trend["trade_date"] = pd.to_datetime(trend["trade_date"], errors="raise")
    trend = trend.loc[trend["index_symbol"].isin(spec["population"]["indices"])].copy()
    _parse_available(trend, "trend")

    breadth_fields = {
        "trade_date",
        "market_view",
        "denominator",
        "view_valid",
        "decision_at",
        "available_at",
        *(state_columns["B1_discovery"].values()),
        *(state_columns["B2_concentration"].values()),
    }
    breadth = pd.read_csv(
        _resolve(spec["inputs"]["breadth_panel"]["path"]),
        usecols=sorted(breadth_fields),
        float_precision="round_trip",
    )
    breadth["trade_date"] = pd.to_datetime(breadth["trade_date"], errors="raise")
    breadth["view_valid"] = _as_bool(breadth["view_valid"])
    breadth = breadth.loc[
        breadth["denominator"].eq(spec["population"]["breadth_denominator"])
        & breadth["market_view"].isin(spec["population"]["market_views"])
        & breadth["view_valid"]
    ].copy()
    _parse_available(breadth, "breadth")
    return breakout, trend, breadth


def _common_calendar(
    spec: dict[str, Any], trend: pd.DataFrame, breadth: pd.DataFrame
) -> list[pd.Timestamp]:
    trend_counts = trend.groupby("trade_date")["index_symbol"].nunique()
    breadth_counts = breadth.groupby("trade_date")["market_view"].nunique()
    trend_dates = set(trend_counts.loc[trend_counts.eq(len(spec["population"]["indices"]))].index)
    breadth_dates = set(
        breadth_counts.loc[breadth_counts.eq(len(spec["population"]["market_views"]))].index
    )
    dates = sorted(trend_dates & breadth_dates)
    if not dates:
        raise BreakoutHabitatError("no complete common state calendar")
    return dates


def _prior_date_map(
    event_dates: pd.Series, state_dates: list[pd.Timestamp]
) -> dict[pd.Timestamp, pd.Timestamp | pd.NaT]:
    state_values = np.array(state_dates, dtype="datetime64[ns]")
    output: dict[pd.Timestamp, pd.Timestamp | pd.NaT] = {}
    for raw_date in sorted(pd.to_datetime(event_dates).unique()):
        event_date = pd.Timestamp(raw_date)
        position = int(np.searchsorted(state_values, event_date.to_datetime64(), side="left")) - 1
        output[event_date] = pd.NaT if position < 0 else pd.Timestamp(state_values[position])
    return output


def _support_pass(
    spec: dict[str, Any], frame: pd.DataFrame, kind: str
) -> tuple[bool, dict[str, Any]]:
    gate = spec["support_gates"][kind]
    counts = {
        "total": len(frame),
        "blocks": {block: int(frame["temporal_block"].eq(block).sum()) for block in ["A", "B"]},
        "years": {
            str(year): int(frame["target_year"].eq(year).sum())
            for year in spec["population"]["years"]
        },
        "views": {
            view: int(frame["market_view"].eq(view).sum())
            for view in spec["population"]["market_views"]
        },
    }
    passed = bool(
        counts["total"] >= gate["total"]
        and all(value >= gate["each_block"] for value in counts["blocks"].values())
        and all(value >= gate["each_year"] for value in counts["years"].values())
        and all(value >= gate["each_view"] for value in counts["views"].values())
    )
    return passed, counts


def _build_state_response_panel(
    spec: dict[str, Any], breakout: pd.DataFrame, trend: pd.DataFrame, breadth: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    state_dates = _common_calendar(spec, trend, breadth)
    date_map = _prior_date_map(breakout["trade_date"], state_dates)
    breakout = breakout.copy()
    breakout["prior_state_date"] = breakout["trade_date"].map(date_map)
    pre_join_rows = len(breakout)
    breakout = breakout.loc[breakout["prior_state_date"].notna()].copy()
    if not bool((breakout["prior_state_date"] < breakout["trade_date"]).all()):
        raise BreakoutHabitatError("prior-state temporal ordering failed")

    breadth_states = breadth.rename(columns={"trade_date": "prior_state_date"})
    trend_states = trend.rename(columns={"trade_date": "prior_state_date"})
    records: list[pd.DataFrame] = []
    support: dict[str, Any] = {
        "input_primary_events": pre_join_rows,
        "events_with_prior_state_date": len(breakout),
        "roles": {},
    }
    for role, role_spec in spec["roles"].items():
        controls = role_spec["controls"]
        flag = role_spec["domain_flag"]
        eligible = breakout.loc[
            breakout[flag] & pd.to_numeric(breakout[role], errors="coerce").notna()
        ].copy()
        eligible = eligible.dropna(subset=controls)
        event_kind = (
            "reacquisition_event_rows_after_prior_join"
            if role == "reacquisition_bars"
            else "main_event_rows_after_prior_join"
        )
        event_pass, event_counts = _support_pass(spec, eligible, event_kind)
        aggregations: dict[str, Any] = {
            "event_count": ("audit_id", "size"),
            "physical_session_count": ("symbol", "nunique"),
            "response": (role, "median"),
        }
        for control in controls:
            aggregations[f"control__{control}"] = (control, "median")
        grouped = (
            eligible.groupby(
                ["trade_date", "prior_state_date", "market_view", "target_year"],
                sort=True,
            )
            .agg(**aggregations)
            .reset_index()
        )
        grouped["temporal_block"] = np.where(grouped["target_year"].le(2020), "A", "B")
        grouped["role"] = role
        cell_kind = (
            "reacquisition_date_view_cells"
            if role == "reacquisition_bars"
            else "main_date_view_cells"
        )
        cell_pass, cell_counts = _support_pass(spec, grouped, cell_kind)
        joined = grouped.merge(
            breadth_states,
            on=["prior_state_date", "market_view"],
            how="inner",
            validate="many_to_one",
        ).merge(
            trend_states,
            on="prior_state_date",
            how="inner",
            validate="many_to_many",
        )
        if len(joined) != len(grouped) * len(spec["population"]["indices"]):
            raise BreakoutHabitatError(f"state join population changed: {role}")
        joined["available_at"] = joined["trade_date"].dt.strftime("%Y-%m-%d") + "T15:30:00+08:00"
        support["roles"][role] = {
            "event_support_pass": event_pass,
            "event_counts": event_counts,
            "cell_support_pass": cell_pass,
            "cell_counts": cell_counts,
            "joined_rows": len(joined),
        }
        records.append(joined)
    panel = pd.concat(records, ignore_index=True, sort=False)
    return panel.sort_values(["role", "trade_date", "market_view", "index_symbol"]).reset_index(
        drop=True
    ), support


def _state_field(spec: dict[str, Any], primitive: str, coordinate: str) -> str:
    return spec["state_primitives"][primitive][coordinate]


def _generic_controls(spec: dict[str, Any], role: str) -> list[str]:
    return [f"control__{field}" for field in spec["roles"][role]["controls"]]


def _evaluate_edges(
    spec: dict[str, Any], panel: pd.DataFrame, support: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    edge_gate = spec["primitive_edge_gate"]
    primitives = list(spec["state_primitives"])
    for role in spec["roles"]:
        role_frame = panel.loc[panel["role"].eq(role)].copy()
        role_support = support["roles"][role]
        cell_min = spec["support_gates"][
            "primitive_cell_reacquisition"
            if role == "reacquisition_bars"
            else "primitive_cell_main"
        ]
        generic = _generic_controls(spec, role)
        for primitive in primitives:
            edge_key = f"{role}|{primitive}"
            coordinate_results: dict[str, Any] = {}
            coordinate_passes: list[bool] = []
            coordinate_signs: list[int] = []
            for coordinate in spec["coordinate_systems"]:
                state = _state_field(spec, primitive, coordinate)
                other_states = [
                    _state_field(spec, other, coordinate)
                    for other in primitives
                    if other != primitive
                ]
                controls = [*generic, *other_states]
                blocks: dict[str, Any] = {}
                block_signs: list[int] = []
                block_passes: list[bool] = []
                for block in ["A", "B"]:
                    correlations: list[float] = []
                    cell_passes: list[bool] = []
                    for index_symbol in spec["population"]["indices"]:
                        for market_view in spec["population"]["market_views"]:
                            cell = role_frame.loc[
                                role_frame["temporal_block"].eq(block)
                                & role_frame["index_symbol"].eq(index_symbol)
                                & role_frame["market_view"].eq(market_view)
                            ]
                            n, rho, response_unique, state_unique = _partial_spearman(
                                cell, "response", state, controls
                            )
                            passed = bool(
                                n >= cell_min
                                and response_unique
                                >= spec["nondegeneracy"][
                                    "minimum_unique_response_per_primitive_cell"
                                ]
                                and state_unique
                                >= spec["nondegeneracy"]["minimum_unique_state_per_primitive_cell"]
                                and np.isfinite(rho)
                            )
                            cell_passes.append(passed)
                            correlations.append(rho)
                            audit.append(
                                {
                                    "role": role,
                                    "primitive": primitive,
                                    "coordinate": coordinate,
                                    "scope": "BLOCK_CELL",
                                    "block": block,
                                    "year": "",
                                    "index_symbol": index_symbol,
                                    "market_view": market_view,
                                    "n": n,
                                    "response_unique": response_unique,
                                    "state_unique": state_unique,
                                    "partial_spearman": rho,
                                    "support_pass": passed,
                                }
                            )
                    finite = np.asarray([value for value in correlations if np.isfinite(value)])
                    median = float(np.median(finite)) if len(finite) else np.nan
                    sign = _sign(median)
                    same_sign = int(sum(_sign(value) == sign for value in finite)) if sign else 0
                    passed = bool(
                        all(cell_passes)
                        and len(finite) == 24
                        and abs(median)
                        >= edge_gate["minimum_median_absolute_partial_spearman_each_block"]
                        and same_sign >= edge_gate["minimum_same_sign_index_view_cells_each_block"]
                    )
                    blocks[block] = {
                        "median_partial_spearman": median,
                        "same_sign_cells": same_sign,
                        "supported_cells": int(sum(cell_passes)),
                        "pass": passed,
                    }
                    block_signs.append(sign)
                    block_passes.append(passed)
                annual_medians: dict[str, float] = {}
                for year in spec["population"]["years"]:
                    correlations = []
                    for index_symbol in spec["population"]["indices"]:
                        year_frame = role_frame.loc[
                            role_frame["target_year"].eq(year)
                            & role_frame["index_symbol"].eq(index_symbol)
                        ]
                        n, rho, response_unique, state_unique = _partial_spearman(
                            year_frame, "response", state, controls
                        )
                        if (
                            response_unique
                            >= spec["nondegeneracy"]["minimum_unique_each_year_pooled"]
                            and state_unique
                            >= spec["nondegeneracy"]["minimum_unique_each_year_pooled"]
                        ):
                            correlations.append(rho)
                        audit.append(
                            {
                                "role": role,
                                "primitive": primitive,
                                "coordinate": coordinate,
                                "scope": "YEAR_INDEX",
                                "block": "",
                                "year": year,
                                "index_symbol": index_symbol,
                                "market_view": "ALL_VIEWS",
                                "n": n,
                                "response_unique": response_unique,
                                "state_unique": state_unique,
                                "partial_spearman": rho,
                                "support_pass": bool(np.isfinite(rho)),
                            }
                        )
                    finite = [value for value in correlations if np.isfinite(value)]
                    annual_medians[str(year)] = (
                        float(np.median(finite)) if len(finite) == 6 else np.nan
                    )
                common_sign = (
                    block_signs[0]
                    if block_signs[0] != 0 and block_signs[0] == block_signs[1]
                    else 0
                )
                annual_same = sum(
                    _sign(value) == common_sign
                    for value in annual_medians.values()
                    if np.isfinite(value)
                )
                coordinate_pass = bool(
                    role_support["event_support_pass"]
                    and role_support["cell_support_pass"]
                    and all(block_passes)
                    and common_sign
                    and annual_same >= edge_gate["minimum_annual_median_sign_agreement"]
                )
                coordinate_results[coordinate] = {
                    "blocks": blocks,
                    "annual_medians": annual_medians,
                    "common_sign": common_sign,
                    "annual_same_sign": annual_same,
                    "pass": coordinate_pass,
                }
                coordinate_passes.append(coordinate_pass)
                coordinate_signs.append(common_sign)
            edge_pass = bool(
                all(coordinate_passes)
                and coordinate_signs[0] != 0
                and len(set(coordinate_signs)) == 1
            )
            summary[edge_key] = {
                "status": "PRIMITIVE_EDGE_PASS" if edge_pass else "PRIMITIVE_EDGE_FAIL",
                "pass": edge_pass,
                "coordinates": coordinate_results,
            }
    return pd.DataFrame(audit), summary


def _evaluate_joint(
    spec: dict[str, Any], panel: pd.DataFrame, support: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    gate = spec["joint_increment_gate"]
    for role in spec["roles"]:
        role_frame = panel.loc[panel["role"].eq(role)]
        generic = _generic_controls(spec, role)
        minimum = spec["support_gates"][
            "joint_block_reacquisition" if role == "reacquisition_bars" else "joint_block_main"
        ]
        coordinate_results: dict[str, Any] = {}
        coordinate_passes: list[bool] = []
        for coordinate in spec["coordinate_systems"]:
            states = [
                _state_field(spec, primitive, coordinate) for primitive in spec["state_primitives"]
            ]
            blocks: dict[str, Any] = {}
            block_passes: list[bool] = []
            for block in ["A", "B"]:
                increments: list[float] = []
                supported: list[bool] = []
                for index_symbol in spec["population"]["indices"]:
                    cell = role_frame.loc[
                        role_frame["temporal_block"].eq(block)
                        & role_frame["index_symbol"].eq(index_symbol)
                    ].dropna(subset=["response", *generic, *states])
                    baseline = _adjusted_rank_r2(cell, "response", generic)
                    full = _adjusted_rank_r2(cell, "response", [*generic, *states])
                    increment = (
                        full - baseline if np.isfinite(full) and np.isfinite(baseline) else np.nan
                    )
                    support_pass = bool(len(cell) >= minimum and np.isfinite(increment))
                    increments.append(increment)
                    supported.append(support_pass)
                    records.append(
                        {
                            "role": role,
                            "coordinate": coordinate,
                            "block": block,
                            "index_symbol": index_symbol,
                            "n": len(cell),
                            "baseline_adjusted_r2": baseline,
                            "full_adjusted_r2": full,
                            "increment": increment,
                            "support_pass": support_pass,
                        }
                    )
                finite = [value for value in increments if np.isfinite(value)]
                median = float(np.median(finite)) if len(finite) == 6 else np.nan
                positive = int(sum(value > 0 for value in finite))
                passed = bool(
                    all(supported)
                    and median >= gate["minimum_median_adjusted_r2_increment_each_block"]
                    and positive >= gate["minimum_positive_indices_each_block"]
                )
                blocks[block] = {
                    "median_increment": median,
                    "positive_indices": positive,
                    "pass": passed,
                }
                block_passes.append(passed)
            coordinate_pass = bool(
                support["roles"][role]["event_support_pass"]
                and support["roles"][role]["cell_support_pass"]
                and all(block_passes)
            )
            coordinate_results[coordinate] = {
                "blocks": blocks,
                "pass": coordinate_pass,
            }
            coordinate_passes.append(coordinate_pass)
        passed = all(coordinate_passes)
        summary[role] = {
            "status": "JOINT_INCREMENT_PASS" if passed else "JOINT_INCREMENT_FAIL",
            "pass": passed,
            "coordinates": coordinate_results,
        }
    return pd.DataFrame(records), summary


def _manual_scalar_audit(
    spec: dict[str, Any], breakout: pd.DataFrame, panel: pd.DataFrame
) -> dict[str, Any]:
    cells = panel.drop_duplicates(["role", "trade_date", "market_view"]).copy()
    cells["selection_hash"] = cells.apply(
        lambda row: hashlib.sha256(
            f"MKT-BREAKOUT-HAB-001|{row.role}|{row.trade_date.date()}|{row.market_view}".encode()
        ).hexdigest(),
        axis=1,
    )
    selected: list[pd.Series] = []
    identities: set[tuple[pd.Timestamp, str]] = set()
    for _, row in cells.sort_values("selection_hash").iterrows():
        identity = (pd.Timestamp(row["trade_date"]), str(row["market_view"]))
        if identity in identities:
            continue
        identities.add(identity)
        selected.append(row)
        if len(selected) == spec["validation"]["manual_scalar_cases"]:
            break
    cases: list[dict[str, Any]] = []
    maximum = 0.0
    for row in selected:
        role = str(row["role"])
        role_spec = spec["roles"][role]
        source = breakout.loc[
            breakout["trade_date"].eq(row["trade_date"])
            & breakout["market_view"].eq(row["market_view"])
            & breakout[role_spec["domain_flag"]]
        ].dropna(subset=[role, *role_spec["controls"]])
        differences = [abs(float(source[role].median()) - float(row["response"]))]
        for control in role_spec["controls"]:
            differences.append(
                abs(float(source[control].median()) - float(row[f"control__{control}"]))
            )
        case_max = max(differences)
        maximum = max(maximum, case_max)
        cases.append(
            {
                "role": role,
                "trade_date": row["trade_date"].date().isoformat(),
                "market_view": row["market_view"],
                "selection_hash": row["selection_hash"],
                "maximum_absolute_difference": case_max,
            }
        )
    if len(cases) != spec["validation"]["manual_scalar_cases"]:
        raise BreakoutHabitatError("manual scalar case support changed")
    if maximum > spec["validation"]["maximum_aggregate_absolute_difference"]:
        raise BreakoutHabitatError("manual scalar audit failed")
    return {"cases": cases, "maximum_aggregate_absolute_difference": maximum}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _report(result: dict[str, Any]) -> str:
    passing_edges = result["passing_primitive_edges"]
    passing_joint = result["passing_joint_roles"]
    return "\n".join(
        [
            "# MKT-BREAKOUT-HAB-001 prior-day state geometry",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Passing primitive edges: {', '.join(passing_edges) or 'none'}.",
            f"- Passing joint-increment roles: {', '.join(passing_joint) or 'none'}.",
            "- Unit: event-date x market-view median; six indices are separate "
            "portability replications.",
            "- Every state row is from the immediately prior governed close.",
            "- No payoff, strategy field, raw minute row, post-2023 data, or CY-011 was read.",
            "",
            "## Boundary",
            "",
            "A passing edge or joint increment is consumed exploratory market-behavior "
            "evidence, not causality, interaction, synergy, a habitat gate, or a "
            "trading rule.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec']}`",
            f"- Runner SHA-256: `{result['hashes']['runner']}`",
            f"- Panel SHA-256: `{result['hashes']['state_response_panel']}`",
            f"- Edge SHA-256: `{result['hashes']['edge_audit']}`",
            f"- Joint SHA-256: `{result['hashes']['joint_audit']}`",
            "",
        ]
    )


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    breakout, trend, breadth = _load_inputs(spec)
    panel, support = _build_state_response_panel(spec, breakout, trend, breadth)
    _resource_guard(spec, started)
    edge_audit, edge_summary = _evaluate_edges(spec, panel, support)
    joint_audit, joint_summary = _evaluate_joint(spec, panel, support)
    scalar = _manual_scalar_audit(spec, breakout, panel)
    passing_edges = [key for key, value in edge_summary.items() if value["pass"]]
    passing_joint = [key for key, value in joint_summary.items() if value["pass"]]
    if passing_edges or passing_joint:
        status = "COMPLETE_PORTABLE_PRIOR_STATE_CONDITIONING_PRESENT"
    else:
        status = "COMPLETE_NO_PORTABLE_PRIOR_STATE_CONDITIONING"
    _write_csv(panel, PANEL_PATH)
    _write_csv(
        edge_audit.sort_values(
            [
                "role",
                "primitive",
                "coordinate",
                "scope",
                "block",
                "year",
                "index_symbol",
                "market_view",
            ]
        ).reset_index(drop=True),
        EDGE_PATH,
    )
    _write_csv(
        joint_audit.sort_values(["role", "coordinate", "block", "index_symbol"]).reset_index(
            drop=True
        ),
        JOINT_PATH,
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "support": support,
        "primitive_edges": edge_summary,
        "joint_increments": joint_summary,
        "passing_primitive_edges": passing_edges,
        "passing_joint_roles": passing_joint,
        "scalar_reconstruction": scalar,
        "population": {
            "state_response_rows": len(panel),
            "unique_role_date_view_cells": len(
                panel[["role", "trade_date", "market_view"]].drop_duplicates()
            ),
            "raw_minute_rows_read": 0,
        },
        "hashes": {
            "spec": _sha256_file(SPEC_PATH),
            "runner": _sha256_file(Path(__file__)),
            "research_map": spec["inputs"]["research_map"]["sha256"],
            "breakout_panel": spec["inputs"]["breakout_panel"]["sha256"],
            "trend_panel": spec["inputs"]["trend_panel"]["sha256"],
            "breadth_panel": spec["inputs"]["breadth_panel"]["sha256"],
            "state_response_panel": _sha256_file(PANEL_PATH),
            "edge_audit": _sha256_file(EDGE_PATH),
            "joint_audit": _sha256_file(JOINT_PATH),
        },
        "future_fields_read": "FUTURE_SAME_SESSION_MARKET_EVENT_STATE_ONLY",
        "strategy_or_payoff_fields_read": False,
        "raw_minute_rows_read": 0,
        "post_2023_data_read": False,
        "cy011_read": False,
        "causal_or_strategy_claim": False,
        "interaction_or_synergy_claim": False,
        "new_strategy_archetype": False,
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    durable = sum(
        path.stat().st_size
        for path in [PANEL_PATH, EDGE_PATH, JOINT_PATH, RESULT_PATH, REPORT_PATH]
    )
    if durable > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise BreakoutHabitatError("durable output ceiling breached")
    _resource_guard(spec, started)
    print(
        json.dumps(
            {
                "status": status,
                "passing_primitive_edges": passing_edges,
                "passing_joint_roles": passing_joint,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
