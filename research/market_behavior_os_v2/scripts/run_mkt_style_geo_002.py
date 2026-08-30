#!/usr/bin/env python3
"""Corrected external geometry of circulating-size market states."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_SCRIPT = PROGRAM / "scripts/run_mkt_style_geo_001.py"
PARENT_SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-GEO-001_spec.json"
SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-GEO-002_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-STYLE-GEO-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-GEO-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-GEO-002_geometry.md"
EXPECTED_PARENT_SPEC_SHA256 = "2bf960c60d5fffcb98bb9442c2d05eb91859b91002baf69eab69b2b98bb6d7c8"
EXPECTED_SPEC_SHA256 = "9860c89319122a920bef848f08d92a8882cf9f644f5a8174768e297c73f7e36a"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")

MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_geo_001", PARENT_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load frozen MKT-STYLE-GEO-001 runner")
parent = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(parent)


class StyleGeometryError(RuntimeError):
    """Fail-closed MKT-STYLE-GEO-002 error."""


sha256_file = parent.sha256_file
_clean = parent._clean
_style_field = parent._style_field
_control_field = parent._control_field
_fields_by_source = parent._fields_by_source
_role_fields = parent._role_fields
_control_fields = parent._control_fields
_coordinate_frame = parent._coordinate_frame
_spearman = parent._spearman
adjusted_rank_r2 = parent.adjusted_rank_r2


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StyleGeometryError("control spec identity mismatch")
    if sha256_file(PARENT_SPEC_PATH) != EXPECTED_PARENT_SPEC_SHA256:
        raise StyleGeometryError("parent scientific design identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if control["inherits_scientific_design_sha256"] != EXPECTED_PARENT_SPEC_SHA256:
        raise StyleGeometryError("control parent identity mismatch")
    if control["status"] != "FROZEN_BEFORE_GEOMETRY_ESTIMATION":
        raise StyleGeometryError("control spec is not frozen before estimation")
    if control["only_semantic_correction"]["coordinate"] != "relative_rank":
        raise StyleGeometryError("unexpected semantic correction")
    spec = parent._load_spec()
    spec["experiment_id"] = control["experiment_id"]
    spec["status"] = control["status"]
    spec["outputs"] = control["outputs"]
    spec["relative_rank_semantics"] = control["only_semantic_correction"]
    return spec


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        return parent.load_bound_inputs(spec)
    except parent.StyleGeometryError as exc:
        raise StyleGeometryError(str(exc)) from exc


def _finite_complete_dates(
    frame: pd.DataFrame,
    required: list[str],
    expected_views: set[str],
) -> tuple[list[pd.DataFrame], list[pd.DataFrame], dict[str, int]]:
    complete: list[pd.DataFrame] = []
    nondegenerate: list[pd.DataFrame] = []
    field_nondegenerate = {field: 0 for field in required}
    for _, date_frame in frame.groupby("trade_date", sort=True):
        if len(date_frame) != len(expected_views):
            continue
        if set(date_frame["market_view"]) != expected_views:
            continue
        values = date_frame[required].replace([np.inf, -np.inf], np.nan)
        if values.isna().any().any():
            continue
        complete.append(date_frame)
        flags = {field: bool(values[field].nunique() > 1) for field in required}
        for field, flag in flags.items():
            field_nondegenerate[field] += int(flag)
        if all(flags.values()):
            nondegenerate.append(date_frame)
    return complete, nondegenerate, field_nondegenerate


def complete_support_audit(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    roles: dict[str, dict[str, str]],
    controls: dict[str, dict[str, str]],
) -> dict[str, Any]:
    minimum = int(spec["gates"]["minimum_group_year_observations"])
    expected_views = set(spec["population"]["views"])
    audit: dict[str, Any] = {}
    for role in spec["required_style_roles"]:
        role_audit: dict[str, Any] = {}
        for coordinate in ("raw", "pit", "relative_to_all"):
            work = _coordinate_frame(panel, spec, coordinate).assign(
                year=lambda value: value["trade_date"].dt.year
            )
            required = [
                roles[role][coordinate],
                *[controls[name][coordinate] for name in spec["control_fields"][role]],
            ]
            cells: dict[str, Any] = {}
            for (view, denominator, year), group in work.groupby(
                ["market_view", "denominator", "year"], sort=True
            ):
                clean = group[required].replace([np.inf, -np.inf], np.nan).dropna()
                nondegenerate = {
                    field: bool(clean[field].nunique() > 1) for field in required
                }
                key = f"{view}:{denominator}:{year}"
                cells[key] = {
                    "observations": int(len(clean)),
                    "nondegenerate": nondegenerate,
                }
                if len(clean) < minimum or not all(nondegenerate.values()):
                    raise StyleGeometryError(
                        f"support failed: {role}:{coordinate}:{key}"
                    )
            role_audit[coordinate] = cells

        work = _coordinate_frame(panel, spec, "relative_rank").assign(
            year=lambda value: value["trade_date"].dt.year
        )
        required = [
            roles[role]["relative_rank"],
            *[controls[name]["relative_rank"] for name in spec["control_fields"][role]],
        ]
        cells = {}
        for (denominator, year), group in work.groupby(
            ["denominator", "year"], sort=True
        ):
            complete, nondegenerate, field_counts = _finite_complete_dates(
                group, required, expected_views
            )
            key = f"{denominator}:{year}"
            cells[key] = {
                "complete_four_view_dates": int(len(complete)),
                "jointly_nondegenerate_four_view_dates": int(len(nondegenerate)),
                "field_nondegenerate_date_counts": field_counts,
            }
            if len(complete) < minimum or len(nondegenerate) < minimum:
                raise StyleGeometryError(
                    f"cross-view support failed: {role}:relative_rank:{key}"
                )
        if len(cells) != 6:
            raise StyleGeometryError(f"relative-rank cell identity failed: {role}")
        role_audit["relative_rank"] = cells
        audit[role] = role_audit
    return audit


def adjusted_within_date_r2(
    frame: pd.DataFrame, target: str, control_fields: list[str]
) -> float:
    required = [target, *control_fields]
    clean = frame[["trade_date", *required]].replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return float("nan")
    values = clean[required].astype(float)
    demeaned = values - values.groupby(clean["trade_date"]).transform("mean")
    response = demeaned[target].to_numpy(dtype=float)
    design = demeaned[control_fields].to_numpy(dtype=float)
    n = len(clean)
    groups = int(clean["trade_date"].nunique())
    p = len(control_fields)
    residual_degrees = n - groups - p
    total_degrees = n - groups
    if residual_degrees <= 0 or total_degrees <= 0:
        return float("nan")
    coefficients = np.linalg.lstsq(design, response, rcond=None)[0]
    residual = response - design @ coefficients
    total_ss = float(response @ response)
    if total_ss <= 0:
        return float("nan")
    r2 = 1.0 - float(residual @ residual) / total_ss
    return float(1.0 - (1.0 - r2) * total_degrees / residual_degrees)


def _relative_rank_cell_frames(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    required: list[str],
) -> dict[str, pd.DataFrame]:
    work = _coordinate_frame(panel, spec, "relative_rank").assign(
        year=lambda value: value["trade_date"].dt.year
    )
    expected_views = set(spec["population"]["views"])
    output: dict[str, pd.DataFrame] = {}
    for (denominator, year), group in work.groupby(
        ["denominator", "year"], sort=True
    ):
        _, nondegenerate, _ = _finite_complete_dates(group, required, expected_views)
        key = f"{denominator}:{year}"
        if not nondegenerate:
            raise StyleGeometryError(f"no eligible relative-rank dates: {key}")
        output[key] = pd.concat(nondegenerate, ignore_index=True)
    if len(output) != 6:
        raise StyleGeometryError("relative-rank estimation cell identity failed")
    return output


def _time_series_coordinate_geometry(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    target: str,
    control_names: list[str],
    control_fields: list[str],
    coordinate: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    work = _coordinate_frame(panel, spec, coordinate)
    pairwise: dict[str, Any] = {}
    grouped = [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in work.groupby(
            ["market_view", "denominator"], sort=True
        )
    ]
    for control_name, control in zip(control_names, control_fields, strict=True):
        by_group = {name: _spearman(group, target, control) for name, group in grouped}
        values = np.asarray(list(by_group.values()), dtype=float)
        if not np.isfinite(values).all():
            raise StyleGeometryError(
                f"pairwise estimate failed: {target}:{control_name}:{coordinate}"
            )
        median = float(np.median(np.abs(values)))
        pairwise[control_name] = {
            "by_group": by_group,
            "median_absolute_spearman": median,
            "maximum_absolute_spearman": float(np.max(np.abs(values))),
            "gate_pass": bool(
                median
                < spec["gates"]["pairwise_external_redundancy_absolute_spearman"]
            ),
        }
    by_group_r2 = {
        name: adjusted_rank_r2(group, target, control_fields) for name, group in grouped
    }
    r2_values = np.asarray(list(by_group_r2.values()), dtype=float)
    if not np.isfinite(r2_values).all():
        raise StyleGeometryError(f"joint estimate failed: {target}:{coordinate}")
    median_r2 = float(np.median(r2_values))
    maximum_r2 = float(np.max(r2_values))
    joint = {
        "by_group": by_group_r2,
        "median_adjusted_rank_r2": median_r2,
        "maximum_adjusted_rank_r2": maximum_r2,
        "gate_pass": bool(
            median_r2
            < spec["gates"]["joint_rank_reconstruction_median_adjusted_r2_maximum"]
            and maximum_r2
            < spec["gates"]["joint_rank_reconstruction_maximum_adjusted_r2"]
        ),
    }
    return pairwise, joint


def _relative_rank_geometry(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    target: str,
    control_names: list[str],
    control_fields: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    required = [target, *control_fields]
    cells = _relative_rank_cell_frames(panel, spec, required)
    pairwise: dict[str, Any] = {}
    for control_name, control in zip(control_names, control_fields, strict=True):
        by_cell: dict[str, Any] = {}
        cell_summaries = []
        for cell_name, cell in cells.items():
            daily = {
                str(date.date()): _spearman(date_frame, target, control)
                for date, date_frame in cell.groupby("trade_date", sort=True)
            }
            values = np.asarray(list(daily.values()), dtype=float)
            if not np.isfinite(values).all():
                raise StyleGeometryError(
                    f"cross-view pairwise estimate failed: {target}:{control_name}:{cell_name}"
                )
            summary = float(np.median(np.abs(values)))
            cell_summaries.append(summary)
            by_cell[cell_name] = {
                "dates": int(len(values)),
                "median_absolute_daily_cross_view_spearman": summary,
                "maximum_absolute_daily_cross_view_spearman": float(
                    np.max(np.abs(values))
                ),
            }
        median = float(np.median(np.asarray(cell_summaries, dtype=float)))
        pairwise[control_name] = {
            "by_denominator_year": by_cell,
            "median_absolute_spearman": median,
            "maximum_absolute_spearman": float(np.max(cell_summaries)),
            "gate_pass": bool(
                median
                < spec["gates"]["pairwise_external_redundancy_absolute_spearman"]
            ),
        }
    by_cell_r2 = {
        name: adjusted_within_date_r2(cell, target, control_fields)
        for name, cell in cells.items()
    }
    r2_values = np.asarray(list(by_cell_r2.values()), dtype=float)
    if not np.isfinite(r2_values).all():
        raise StyleGeometryError(f"cross-view joint estimate failed: {target}")
    median_r2 = float(np.median(r2_values))
    maximum_r2 = float(np.max(r2_values))
    joint = {
        "by_denominator_year": by_cell_r2,
        "median_adjusted_rank_r2": median_r2,
        "maximum_adjusted_rank_r2": maximum_r2,
        "gate_pass": bool(
            median_r2
            < spec["gates"]["joint_rank_reconstruction_median_adjusted_r2_maximum"]
            and maximum_r2
            < spec["gates"]["joint_rank_reconstruction_maximum_adjusted_r2"]
        ),
    }
    return pairwise, joint


def estimate_geometry(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    roles: dict[str, dict[str, str]],
    controls: dict[str, dict[str, str]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for role in spec["required_style_roles"]:
        pairwise: dict[str, Any] = {}
        joint: dict[str, Any] = {}
        control_names = spec["control_fields"][role]
        for coordinate in COORDINATES:
            target = roles[role][coordinate]
            control_fields = [controls[name][coordinate] for name in control_names]
            if coordinate == "relative_rank":
                coordinate_pairs, coordinate_joint = _relative_rank_geometry(
                    panel, spec, target, control_names, control_fields
                )
            else:
                coordinate_pairs, coordinate_joint = _time_series_coordinate_geometry(
                    panel,
                    spec,
                    target,
                    control_names,
                    control_fields,
                    coordinate,
                )
            pairwise[coordinate] = coordinate_pairs
            joint[coordinate] = coordinate_joint
        pairwise_pass = all(
            item["gate_pass"]
            for coordinate in pairwise.values()
            for item in coordinate.values()
        )
        joint_pass = all(item["gate_pass"] for item in joint.values())
        classification = (
            "DISTINCT_ENGINE_COORDINATE"
            if pairwise_pass and joint_pass
            else "PAIRWISE_REDUNDANT"
            if not pairwise_pass
            else "JOINTLY_RECONSTRUCTABLE"
        )
        output[role] = {
            "target_fields": roles[role],
            "fixed_controls": control_names,
            "pairwise": pairwise,
            "joint": joint,
            "pairwise_gate_pass": pairwise_pass,
            "joint_gate_pass": joint_pass,
            "classification": classification,
        }
    return output


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-STYLE-GEO-002 circulating-size external geometry",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Common population: {result['population']['rows']:,} rows in "
        f"{result['population']['groups']} groups.",
        "- Relative rank uses matched same-date four-view geometry with date fixed effects.",
        "- Future values, strategy outcomes, failed controls/roles, post-2023 data, and CY-011 read: **none**.",
        "- Distinctness is contemporaneous representation geometry, not causality, size premium, timing, habitat, or a rule.",
        "",
        "## Role geometry",
        "",
        "| Role | Largest pairwise median abs rho | Largest joint median adj R2 | Largest joint max adj R2 | Classification |",
        "|---|---:|---:|---:|---|",
    ]
    for role in spec["required_style_roles"]:
        item = result["role_diagnostics"][role]
        pairwise_max = max(
            value["median_absolute_spearman"]
            for coordinate in item["pairwise"].values()
            for value in coordinate.values()
        )
        joint_median = max(
            value["median_adjusted_rank_r2"] for value in item["joint"].values()
        )
        joint_max = max(
            value["maximum_adjusted_rank_r2"] for value in item["joint"].values()
        )
        lines.append(
            f"| `{role}` | {pairwise_max:.3f} | {joint_median:.3f} | "
            f"{joint_max:.3f} | {item['classification']} |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Parent spec SHA-256: `{result['hashes']['parent_spec_sha256']}`",
            f"- Control spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel, input_audit = load_bound_inputs(spec)
    roles = _role_fields(spec)
    controls = _control_fields(spec)
    support = complete_support_audit(panel, spec, roles, controls)
    diagnostics = estimate_geometry(panel, spec, roles, controls)
    distinct = [
        role
        for role in spec["required_style_roles"]
        if diagnostics[role]["classification"] == "DISTINCT_ENGINE_COORDINATE"
    ]
    pairwise = [
        role
        for role in spec["required_style_roles"]
        if diagnostics[role]["classification"] == "PAIRWISE_REDUNDANT"
    ]
    joint = [
        role
        for role in spec["required_style_roles"]
        if diagnostics[role]["classification"] == "JOINTLY_RECONSTRUCTABLE"
    ]
    output_fields = list(
        dict.fromkeys(
            [
                *[field for mapping in roles.values() for field in mapping.values()],
                *[field for mapping in controls.values() for field in mapping.values()],
            ]
        )
    )
    output = panel[[*KEYS, "geometry_decision_at", *output_fields]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    control_spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": (
            f"COMPLETE_{len(distinct)}_OF_{len(spec['required_style_roles'])}"
            "_DISTINCT_ENGINE_COORDINATES"
        ),
        "usefulness_claim": "NONE",
        "future_values_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_controls_or_style_roles_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "invalid_predecessor": control_spec["invalid_predecessor"],
        "relative_rank_semantics": spec["relative_rank_semantics"],
        "input_audit": input_audit,
        "population": {
            "rows": int(len(output)),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
        },
        "complete_support_audit": support,
        "role_diagnostics": diagnostics,
        "compression": {
            "distinct_engine_coordinates": distinct,
            "pairwise_redundant": pairwise,
            "jointly_reconstructable": joint,
        },
        "hashes": {
            "parent_spec_sha256": sha256_file(PARENT_SPEC_PATH),
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "bound_input_sha256": {
                source: {
                    "panel": entries["panel"]["sha256"],
                    "result": entries["result"]["sha256"],
                }
                for source, entries in spec["inputs"].items()
            },
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result, spec), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "compression": completed["compression"],
                "panel_sha256": completed["hashes"]["panel_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
