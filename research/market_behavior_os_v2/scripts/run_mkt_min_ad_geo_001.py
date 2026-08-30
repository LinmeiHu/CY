#!/usr/bin/env python3
"""Cross-family geometry for rally distribution and breakout levels."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-AD-GEO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-AD-GEO-001_panel.csv"
PAIRWISE_PATH = PROGRAM / "artifacts/MKT-MIN-AD-GEO-001_pairwise_audit.csv"
JOINT_PATH = PROGRAM / "artifacts/MKT-MIN-AD-GEO-001_joint_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-AD-GEO-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-AD-GEO-001_geometry.md"
EXPECTED_SPEC_SHA256 = "f5018ec20b3cc555b59ee244081f748e9836e79eda68d26cbbb1188d6705a93d"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("pit", "relative_to_all", "relative_rank")


class RallyBreakoutGeometryError(RuntimeError):
    """Fail-closed MKT-MIN-AD-GEO-001 error."""


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
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise RallyBreakoutGeometryError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CROSS_FAMILY_GEOMETRY_ESTIMATES":
        raise RallyBreakoutGeometryError("geometry activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise RallyBreakoutGeometryError(f"input identity mismatch: {name}")
    rally = json.loads(_resolve(spec["inputs"]["rally_result"]["path"]).read_text())
    if (
        rally["compression"]["accepted_hypotheses"] != ["rally_effort_distribution"]
        or rally["usefulness_claim"] != "NONE"
        or rally["future_state_fields_read"]
        or rally["strategy_or_outcome_fields_read"]
        or rally["raw_minute_rows_read"]
        or rally["cy011_read"]
    ):
        raise RallyBreakoutGeometryError("rally parent activation changed")
    breakout = json.loads(_resolve(spec["inputs"]["breakout_result"]["path"]).read_text())
    if breakout["minimal_panel"]["accepted_roles"] != list(spec["breakout_roles"]):
        raise RallyBreakoutGeometryError("breakout parent activation changed")
    vwap = json.loads(_resolve(spec["inputs"]["vwap_result"]["path"]).read_text())
    if vwap["compression"]["accepted_mechanisms"] != ["vwap_defense_recovery"]:
        raise RallyBreakoutGeometryError("VWAP parent activation changed")
    return spec


def _breakout_field(raw: str, coordinate: str) -> str:
    suffix = {
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def load_panel(spec: dict[str, Any]) -> pd.DataFrame:
    target_fields = [_target(spec, coordinate) for coordinate in COORDINATES]
    return_spec = spec["fixed_alternatives"]["open_close_return"]
    rally_columns = [
        *KEYS,
        "available_at",
        *target_fields,
        return_spec["raw"],
        return_spec["pit"],
        return_spec["relative_rank"],
    ]
    rally = pd.read_csv(_resolve(spec["inputs"]["rally_panel"]["path"]), usecols=rally_columns)
    breakout_columns = [*KEYS, "decision_at", "available_at"]
    for raw in spec["breakout_roles"].values():
        breakout_columns.extend(_breakout_field(raw, coordinate) for coordinate in COORDINATES)
    breakout = pd.read_csv(
        _resolve(spec["inputs"]["breakout_panel"]["path"]),
        usecols=list(dict.fromkeys(breakout_columns)),
    )
    vwap_spec = spec["fixed_alternatives"]["vwap_defense_recovery"]
    vwap = pd.read_csv(
        _resolve(spec["inputs"]["vwap_panel"]["path"]),
        usecols=[*KEYS, *vwap_spec.values()],
    )
    for label, frame in (("rally", rally), ("breakout", breakout), ("vwap", vwap)):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
        if frame.duplicated(KEYS).any() or frame["trade_date"].max() > pd.Timestamp("2023-12-31"):
            raise RallyBreakoutGeometryError(f"{label} key/date boundary changed")
    joined = breakout.merge(rally, on=KEYS, how="left", validate="one_to_one").merge(
        vwap, on=KEYS, how="left", validate="one_to_one"
    )
    population = spec["population"]
    if (
        len(joined) != population["expected_rows"]
        or str(joined["trade_date"].min().date()) != population["date_start"]
        or str(joined["trade_date"].max().date()) != population["date_end"]
    ):
        raise RallyBreakoutGeometryError("joined population changed")
    counts = joined.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not counts.eq(population["expected_rows_per_group"]).all():
        raise RallyBreakoutGeometryError("joined group population changed")
    rally_time = pd.to_datetime(joined["available_at_y"], errors="raise")
    breakout_time = pd.to_datetime(joined["available_at_x"], errors="raise")
    if (
        not rally_time.dt.strftime("%H:%M:%S").eq("15:30:00").all()
        or not breakout_time.dt.strftime("%H:%M:%S").eq("15:00:00").all()
        or not (rally_time.dt.date == joined["trade_date"].dt.date).all()
    ):
        raise RallyBreakoutGeometryError("joint availability changed")
    raw_return = return_spec["raw"]
    joined["open_close_return__relative_to_all"] = np.nan
    for _, index in joined.groupby(["trade_date", "denominator"], sort=True).groups.items():
        cell = joined.loc[index]
        all_a = cell.loc[cell["market_view"].eq("ALL_A"), raw_return]
        if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
            continue
        joined.loc[index, "open_close_return__relative_to_all"] = cell[raw_return] - float(
            all_a.iloc[0]
        )
    joined["joint_available_at"] = joined["available_at_y"]
    return joined.sort_values(KEYS).reset_index(drop=True)


def _target(spec: dict[str, Any], coordinate: str) -> str:
    return spec["target"][coordinate]


def _alternatives(spec: dict[str, Any], coordinate: str) -> list[str]:
    return_spec = spec["fixed_alternatives"]["open_close_return"]
    return_field = (
        "open_close_return__relative_to_all"
        if coordinate == "relative_to_all"
        else return_spec[coordinate]
    )
    vwap_field = spec["fixed_alternatives"]["vwap_defense_recovery"][coordinate]
    return [return_field, vwap_field]


def _controls(spec: dict[str, Any], coordinate: str) -> list[str]:
    return [
        *[_breakout_field(raw, coordinate) for raw in spec["breakout_roles"].values()],
        *_alternatives(spec, coordinate),
    ]


def _analysis_groups(frame: pd.DataFrame, coordinate: str) -> list[tuple[str, pd.DataFrame]]:
    if coordinate == "relative_rank":
        return [
            (str(denominator), group)
            for denominator, group in frame.groupby("denominator", sort=True)
        ]
    if coordinate == "relative_to_all":
        frame = frame.loc[frame["market_view"].ne("ALL_A")]
    return [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in frame.groupby(["market_view", "denominator"], sort=True)
    ]


def _spearman(frame: pd.DataFrame, left: str, right: str) -> tuple[float, int]:
    clean = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean[left].nunique() < 2 or clean[right].nunique() < 2:
        return float("nan"), len(clean)
    return float(clean.corr(method="spearman").iloc[0, 1]), len(clean)


def _adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> tuple[float, int]:
    clean = frame[[target, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(clean)
    p = len(controls)
    if n <= p + 2 or clean[target].nunique() < 2:
        return float("nan"), n
    ranked = clean.rank(method="average", pct=True)
    y = ranked[target].to_numpy(dtype=float)
    x = np.column_stack([np.ones(n), ranked[controls].to_numpy(dtype=float)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    total = float(np.square(y - y.mean()).sum())
    if total == 0.0:
        return float("nan"), n
    r2 = 1.0 - float(np.square(y - fitted).sum()) / total
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1)), n


def geometry(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    pair_rows: list[dict[str, Any]] = []
    joint_rows: list[dict[str, Any]] = []
    minimum = spec["gates"]["minimum_complete_observations_per_cell_block"]
    for block, years in spec["population"]["blocks"].items():
        block_frame = panel.loc[panel["trade_date"].dt.year.isin(years)]
        for coordinate in COORDINATES:
            target = _target(spec, coordinate)
            for group_name, group in _analysis_groups(block_frame, coordinate):
                for role, raw in spec["breakout_roles"].items():
                    rho, n = _spearman(group, target, _breakout_field(raw, coordinate))
                    pair_rows.append(
                        {
                            "block": block,
                            "coordinate": coordinate,
                            "group": group_name,
                            "breakout_role": role,
                            "n": n,
                            "spearman": rho,
                            "support_pass": n >= minimum and np.isfinite(rho),
                        }
                    )
                adjusted, n = _adjusted_rank_r2(group, target, _controls(spec, coordinate))
                joint_rows.append(
                    {
                        "block": block,
                        "coordinate": coordinate,
                        "group": group_name,
                        "n": n,
                        "adjusted_rank_r2": adjusted,
                        "support_pass": n >= minimum and np.isfinite(adjusted),
                    }
                )
    pairwise = pd.DataFrame(pair_rows)
    joint = pd.DataFrame(joint_rows)
    role_summary: dict[str, Any] = {}
    for role, group in pairwise.groupby("breakout_role", sort=True):
        finite = group["spearman"].dropna().abs()
        role_summary[str(role)] = {
            "cells": len(group),
            "minimum_n": int(group["n"].min()),
            "maximum_absolute_spearman": float(finite.max()),
            "all_support_pass": bool(group["support_pass"].all()),
        }
    joint_summary: dict[str, Any] = {}
    for (block, coordinate), group in joint.groupby(["block", "coordinate"], sort=True):
        values = group["adjusted_rank_r2"].dropna()
        joint_summary[f"{block}:{coordinate}"] = {
            "cells": len(group),
            "minimum_n": int(group["n"].min()),
            "median_adjusted_rank_r2": float(values.median()),
            "maximum_adjusted_rank_r2": float(values.max()),
            "all_support_pass": bool(group["support_pass"].all()),
        }
    pairwise_pass = bool(
        pairwise["support_pass"].all()
        and pairwise["spearman"].abs().max()
        < spec["gates"]["pairwise_redundancy_absolute_spearman"]
    )
    joint_pass = all(
        item["all_support_pass"]
        and item["median_adjusted_rank_r2"]
        < spec["gates"]["joint_rank_reconstruction_median_adjusted_r2_maximum"]
        and item["maximum_adjusted_rank_r2"]
        < spec["gates"]["joint_rank_reconstruction_maximum_adjusted_r2"]
        for item in joint_summary.values()
    )
    summary = {
        "pairwise_by_role": role_summary,
        "maximum_pairwise_absolute_spearman": float(pairwise["spearman"].abs().max()),
        "pairwise_gate_pass": pairwise_pass,
        "joint_by_block_coordinate": joint_summary,
        "joint_gate_pass": joint_pass,
        "distinct_engine_coordinate": bool(pairwise_pass and joint_pass),
    }
    return summary, pairwise, joint


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    geometry_result = result["geometry"]
    lines = [
        "# MKT-MIN-AD-GEO-001 rally-distribution/breakout geometry",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        "- Joint availability is 15:30 after completed same-session inputs.",
        "- Future values, outcomes, strategies, raw security/minute rows, post-2023 "
        "data, and CY-011 read: **none**.",
        "- Geometry establishes neither participant distribution nor future resistance/reversal.",
        "- Maximum pairwise absolute rho: "
        f"{geometry_result['maximum_pairwise_absolute_spearman']:.3f}.",
        "",
        "## Pairwise breakout roles",
        "",
        "| Role | Min n | Max absolute rho | Support |",
        "|---|---:|---:|---|",
    ]
    for role in spec["breakout_roles"]:
        item = geometry_result["pairwise_by_role"][role]
        lines.append(
            f"| {role} | {item['minimum_n']} | {item['maximum_absolute_spearman']:.3f} | "
            f"{'PASS' if item['all_support_pass'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Joint reconstruction",
            "",
            "| Block/coordinate | Min n | Median adjusted R2 | Max adjusted R2 | Support |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for name, item in geometry_result["joint_by_block_coordinate"].items():
        lines.append(
            f"| {name} | {item['minimum_n']} | {item['median_adjusted_rank_r2']:.3f} | "
            f"{item['maximum_adjusted_rank_r2']:.3f} | "
            f"{'PASS' if item['all_support_pass'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Runner SHA-256: `{result['hashes']['runner_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
            f"- Pairwise audit SHA-256: `{result['hashes']['pairwise_sha256']}`",
            f"- Joint audit SHA-256: `{result['hashes']['joint_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel = load_panel(spec)
    geometry_result, pairwise, joint = geometry(panel, spec)
    output = panel.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    pairwise.to_csv(PAIRWISE_PATH, index=False, float_format="%.12g", lineterminator="\n")
    joint.to_csv(JOINT_PATH, index=False, float_format="%.12g", lineterminator="\n")
    all_support = bool(
        all(item["all_support_pass"] for item in geometry_result["pairwise_by_role"].values())
        and all(
            item["all_support_pass"]
            for item in geometry_result["joint_by_block_coordinate"].values()
        )
    )
    if geometry_result["distinct_engine_coordinate"]:
        status = "COMPLETE_DISTINCT_CROSS_FAMILY_COORDINATE"
    elif not all_support:
        status = "COMPLETE_CROSS_FAMILY_SUPPORT_FAIL"
    elif not geometry_result["pairwise_gate_pass"]:
        status = "COMPLETE_CROSS_FAMILY_PAIRWISE_REDUNDANCY"
    else:
        status = "COMPLETE_CROSS_FAMILY_JOINT_RECONSTRUCTION_FAILS_DISTINCTNESS"
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "usefulness_claim": "NONE",
        "participant_distribution_claim": "NONE",
        "future_resistance_reversal_claim": "NONE",
        "future_values_read": False,
        "strategy_or_outcome_fields_read": [],
        "raw_security_rows_read": 0,
        "raw_minute_rows_read": 0,
        "post_2023_rows_read": 0,
        "cy011_read": False,
        "population": {
            "rows": len(panel),
            "groups": panel.groupby(["market_view", "denominator"]).ngroups,
            "first_date": str(panel["trade_date"].min().date()),
            "last_date": str(panel["trade_date"].max().date()),
            "joint_available_at": "15:30 Asia/Shanghai",
        },
        "geometry": geometry_result,
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "runner_sha256": sha256_file(Path(__file__)),
            "rally_panel_sha256": spec["inputs"]["rally_panel"]["sha256"],
            "breakout_panel_sha256": spec["inputs"]["breakout_panel"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
            "pairwise_sha256": sha256_file(PAIRWISE_PATH),
            "joint_sha256": sha256_file(JOINT_PATH),
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
                "distinct": final["geometry"]["distinct_engine_coordinate"],
                "maximum_pairwise_absolute_spearman": final["geometry"][
                    "maximum_pairwise_absolute_spearman"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
