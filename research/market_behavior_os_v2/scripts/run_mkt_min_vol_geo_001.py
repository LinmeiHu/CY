#!/usr/bin/env python3
"""Outcome-blind geometry of the accepted five-day minute-volatility path."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-VOL-GEO-002_spec.json"
PARENT_SPEC_PATH = PROGRAM / "experiments/MKT-MIN-VOL-GEO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-GEO-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-GEO-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-VOL-GEO-002_geometry.md"
EXPECTED_SPEC_SHA256 = "b556472dc456a1d9faefda98a6de01751d9254816bf283e5c2abd7a1c50024c4"
EXPECTED_PARENT_SPEC_SHA256 = "d1f67d059c5c08311618b255e0b7c684642c773bbad815029b57bdcc0bbce475"
KEYS = ["trade_date", "market_view", "denominator"]


class MinuteVolatilityGeometryError(RuntimeError):
    """Fail-closed MKT-MIN-VOL-GEO-001 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _spearman(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def _local_timestamp(series: pd.Series, naive_local: bool) -> pd.Series:
    parsed = pd.to_datetime(series, errors="raise")
    if naive_local:
        if parsed.dt.tz is not None:
            raise MinuteVolatilityGeometryError("expected naive local timestamp")
        return parsed.dt.tz_localize("Asia/Shanghai")
    if parsed.dt.tz is None:
        raise MinuteVolatilityGeometryError("expected offset-aware timestamp")
    return parsed.dt.tz_convert("Asia/Shanghai")


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise MinuteVolatilityGeometryError("spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if sha256_file(PARENT_SPEC_PATH) != EXPECTED_PARENT_SPEC_SHA256:
        raise MinuteVolatilityGeometryError("parent scientific design identity mismatch")
    if control["inherits_scientific_design_sha256"] != EXPECTED_PARENT_SPEC_SHA256:
        raise MinuteVolatilityGeometryError("control parent identity mismatch")
    parent = json.loads(PARENT_SPEC_PATH.read_text(encoding="utf-8"))
    spec = json.loads(json.dumps(parent))
    spec["experiment_id"] = control["experiment_id"]
    spec["status"] = control["status"]
    spec["outputs"] = control["outputs"]
    correction = control["only_semantic_correction"]
    spec["population"].pop("eligible_years_for_cell_gate", None)
    spec["population"]["raw_cell_years"] = correction["raw_cell_years"]
    spec["population"]["pit_cell_and_geometry_years"] = correction["pit_cell_and_geometry_years"]
    spec["population"]["relative_cell_and_geometry_years"] = correction["relative_cell_and_geometry_years"]
    if spec["status"] != "FROZEN_BEFORE_GEOMETRY_RESULT":
        raise MinuteVolatilityGeometryError("spec is not frozen before result")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name in ("path_panel", "path_result", "volatility_panel", "volatility_result"):
        entry = spec["inputs"][name]
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise MinuteVolatilityGeometryError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_source_results(paths: dict[str, Path]) -> None:
    path_result = json.loads(paths["path_result"].read_text(encoding="utf-8"))
    accepted_path = path_result["diagnostics"]["minimal_panel"]["accepted_roles"]
    if accepted_path != ["minute_realized_volatility__ordinal_progression"]:
        raise MinuteVolatilityGeometryError("path result no longer has the exact sole accepted role")
    vol_result = json.loads(paths["volatility_result"].read_text(encoding="utf-8"))
    accepted_vol = vol_result["minimal_panel"]["accepted_roles"]
    expected = ["realized_volatility", "intraday_range", "volatility_concentration", "volatility_change"]
    if accepted_vol != expected:
        raise MinuteVolatilityGeometryError("volatility accepted-role identity mismatch")


def _allowed_columns(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    target = spec["target"]
    path_columns = [*KEYS, "available_at", "hard_valid", target["raw"], target["pit"],
                    target["relative_to_all"], target["relative_rank"]]
    vol_columns = [*KEYS, "decision_at", "available_at", "view_valid"]
    for control in spec["controls"].values():
        for coordinate in ("raw", "pit", "relative_to_all", "relative_rank"):
            column = control[coordinate]
            if column is None:
                continue
            if control["source"] == "path_panel":
                path_columns.append(column)
            else:
                vol_columns.append(column)
    return list(dict.fromkeys(path_columns)), list(dict.fromkeys(vol_columns))


def load_bound_inputs(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_source_results(paths)
    path_columns, vol_columns = _allowed_columns(spec)
    path = pd.read_csv(paths["path_panel"], usecols=path_columns)
    vol = pd.read_csv(paths["volatility_panel"], usecols=vol_columns)
    for name, frame in (("path", path), ("volatility", vol)):
        if frame.duplicated(KEYS).any():
            raise MinuteVolatilityGeometryError(f"duplicate {name} keys")
    if not path["hard_valid"].astype(bool).all() or not vol["view_valid"].astype(bool).all():
        raise MinuteVolatilityGeometryError("invalid source row entered geometry")

    start = pd.Timestamp(spec["inputs"]["date_start"])
    end = pd.Timestamp(spec["inputs"]["date_end"])
    for frame in (path, vol):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    path = path.loc[path["trade_date"].between(start, end)].copy()
    vol = vol.loc[vol["trade_date"].between(start, end)].copy()
    if len(path) != spec["population"]["expected_rows"] or len(vol) != spec["population"]["expected_rows"]:
        raise MinuteVolatilityGeometryError("common source row count mismatch")

    path_time = _local_timestamp(path["available_at"], naive_local=True)
    vol_time = _local_timestamp(vol["available_at"], naive_local=False)
    vol_decision = _local_timestamp(vol["decision_at"], naive_local=False)
    if not (path_time.dt.strftime("%H:%M:%S") == "15:30:00").all():
        raise MinuteVolatilityGeometryError("path availability is not exact 15:30")
    if not (vol_time.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise MinuteVolatilityGeometryError("volatility availability is not exact 15:00")
    if (vol_time > vol_decision).any():
        raise MinuteVolatilityGeometryError("volatility time travel")
    if not (path_time.dt.date == path["trade_date"].dt.date).all():
        raise MinuteVolatilityGeometryError("path date/availability mismatch")

    path = path.rename(columns={"available_at": "available_at_path"})
    vol = vol.rename(columns={"available_at": "available_at_volatility",
                              "decision_at": "decision_at_volatility"})
    merged = path.merge(vol, on=KEYS, how="outer", indicator=True, validate="one_to_one")
    if not (merged["_merge"] == "both").all():
        raise MinuteVolatilityGeometryError("path/volatility key-set mismatch")
    merged = merged.drop(columns="_merge")
    merged["geometry_decision_at"] = merged["trade_date"].dt.strftime("%Y-%m-%dT15:30:00+08:00")
    merged["available_at_path"] = pd.to_datetime(merged["available_at_path"]).dt.strftime("%Y-%m-%dT15:30:00")

    expected_views = set(spec["population"]["views"])
    expected_denominators = set(spec["population"]["denominators"])
    if set(merged["market_view"]) != expected_views or set(merged["denominator"]) != expected_denominators:
        raise MinuteVolatilityGeometryError("view/denominator identity mismatch")
    counts = merged.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != spec["gates"]["exact_groups"] or not (
        counts == spec["population"]["expected_rows_per_group"]
    ).all():
        raise MinuteVolatilityGeometryError("exact group population mismatch")
    return merged.sort_values(KEYS).reset_index(drop=True)


def _assert_cell_support(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, int]:
    target = spec["target"]
    raw_fields = [target["raw"], *[item["raw"] for item in spec["controls"].values()]]
    pit_fields = [target["pit"], *[
        item["pit"] for item in spec["controls"].values() if item["pit"] is not None
    ]]
    minimum = spec["gates"]["group_year_minimum_observations"]
    diagnostics: dict[str, int] = {}
    work = panel.assign(year=panel["trade_date"].dt.year)
    for (view, denominator, year), group in work.groupby(["market_view", "denominator", "year"], sort=True):
        year_fields: list[str] = []
        if int(year) in spec["population"]["raw_cell_years"]:
            year_fields.extend(raw_fields)
        if int(year) in spec["population"]["pit_cell_and_geometry_years"]:
            year_fields.extend(pit_fields)
        for field in year_fields:
            finite = pd.to_numeric(group[field], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
            key = f"{view}:{denominator}:{year}:{field}"
            diagnostics[key] = int(len(finite))
            if len(finite) < minimum or finite.nunique() < 2:
                raise MinuteVolatilityGeometryError(f"group/year support failed: {key}")
    for denominator, group in work.groupby("denominator", sort=True):
        for year in spec["population"]["relative_cell_and_geometry_years"]:
            cell = group.loc[group["year"] == year]
            for coordinate in ("relative_to_all", "relative_rank"):
                fields = [target[coordinate], *[
                    item[coordinate] for item in spec["controls"].values()
                    if item[coordinate] is not None
                ]]
                for field in fields:
                    finite = pd.to_numeric(cell[field], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
                    key = f"{denominator}:{year}:{coordinate}:{field}"
                    diagnostics[key] = int(len(finite))
                    if len(finite) < minimum * 4 or finite.nunique() < 2:
                        raise MinuteVolatilityGeometryError(f"relative year support failed: {key}")
    return diagnostics


def _pairwise_geometry(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    target = spec["target"]
    threshold = spec["gates"]["pairwise_median_absolute_spearman_strictly_below"]
    output: dict[str, Any] = {}
    for name, control in spec["controls"].items():
        views: dict[str, Any] = {}
        for coordinate in ("raw", "pit"):
            if control[coordinate] is None:
                continue
            coordinate_panel = panel
            if coordinate == "pit":
                coordinate_panel = panel.loc[
                    panel["trade_date"].dt.year.isin(spec["population"]["pit_cell_and_geometry_years"])
                ]
            pairs: dict[str, float] = {}
            for (view, denominator), group in coordinate_panel.groupby(["market_view", "denominator"], sort=True):
                pairs[f"{view}:{denominator}"] = _spearman(group[target[coordinate]], group[control[coordinate]])
            values = np.asarray(list(pairs.values()), dtype=float)
            if not np.isfinite(values).all():
                raise MinuteVolatilityGeometryError(f"nonfinite {name} {coordinate} geometry")
            views[coordinate] = {
                "pairs": pairs,
                "median_absolute_spearman": float(np.median(np.abs(values))),
                "maximum_absolute_spearman": float(np.max(np.abs(values))),
                "median_gate_pass": bool(np.median(np.abs(values)) < threshold),
            }
        if control["relative_to_all"] is not None:
            relative_panel = panel.loc[
                panel["trade_date"].dt.year.isin(spec["population"]["relative_cell_and_geometry_years"])
            ]
            for coordinate in ("relative_to_all", "relative_rank"):
                pairs = {}
                for denominator, group in relative_panel.groupby("denominator", sort=True):
                    pairs[str(denominator)] = _spearman(group[target[coordinate]], group[control[coordinate]])
                values = np.asarray(list(pairs.values()), dtype=float)
                if not np.isfinite(values).all():
                    raise MinuteVolatilityGeometryError(f"nonfinite {name} {coordinate} geometry")
                views[coordinate] = {
                    "pairs": pairs,
                    "median_absolute_spearman": float(np.median(np.abs(values))),
                    "maximum_absolute_spearman": float(np.max(np.abs(values))),
                    "median_gate_pass": bool(np.median(np.abs(values)) < threshold),
                }
        output[name] = {
            "views": views,
            "pairwise_distinct": bool(all(item["median_gate_pass"] for item in views.values())),
        }
    return output


def adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    clean = frame[[target, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(controls) + 2:
        return float("nan")
    ranked = clean.rank(method="average")
    y = ranked[target].to_numpy(float)
    x = np.column_stack([np.ones(len(ranked)), ranked[controls].to_numpy(float)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    residual_sum = float(np.square(y - fitted).sum())
    total_sum = float(np.square(y - y.mean()).sum())
    if total_sum <= 0.0:
        return float("nan")
    r2 = 1.0 - residual_sum / total_sum
    n = len(ranked)
    p = len(controls)
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _joint_geometry(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    target = spec["target"]["raw"]
    controls = [item["raw"] for item in spec["controls"].values()]
    groups: dict[str, float] = {}
    for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
        groups[f"{view}:{denominator}"] = adjusted_rank_r2(group, target, controls)
    values = np.asarray(list(groups.values()), dtype=float)
    if not np.isfinite(values).all():
        raise MinuteVolatilityGeometryError("nonfinite joint rank reconstruction")
    median = float(np.median(values))
    maximum = float(np.max(values))
    return {
        "groups": groups,
        "median_adjusted_r2": median,
        "maximum_adjusted_r2": maximum,
        "median_gate_pass": bool(
            median < spec["gates"]["joint_rank_reconstruction_median_adjusted_r2_strictly_below"]
        ),
        "maximum_gate_pass": bool(
            maximum < spec["gates"]["joint_rank_reconstruction_max_adjusted_r2_strictly_below"]
        ),
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-MIN-VOL-GEO-002 outcome-blind minute-volatility geometry",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Common rows: {result['population']['rows']:,}; {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Geometry availability/decision time: 15:30 Asia/Shanghai after the completed 15:00 minute bar; no action created.",
        "- Raw minutes, failed representations, outcomes, strategy fields, and CY-011 read: **none**.",
        "- Distinctness is contemporaneous state geometry, not contraction/expansion, usefulness, prediction, habitat fitness, or causality.",
        "",
        "## Pairwise geometry",
        "",
        "| Control | Coordinate | Median absolute rho | Maximum absolute rho | Median <0.85 |",
        "|---|---|---:|---:|---|",
    ]
    for control, diagnostic in result["pairwise_geometry"].items():
        for coordinate, view in diagnostic["views"].items():
            lines.append(
                f"| `{control}` | {coordinate} | {view['median_absolute_spearman']:.3f} | "
                f"{view['maximum_absolute_spearman']:.3f} | {'PASS' if view['median_gate_pass'] else 'FAIL'} |"
            )
    joint = result["joint_rank_reconstruction"]
    lines.extend([
        "",
        "## Joint raw-rank reconstruction",
        "",
        f"- Median adjusted R-squared: {joint['median_adjusted_r2']:.3f} (gate <0.70: {'PASS' if joint['median_gate_pass'] else 'FAIL'}).",
        f"- Maximum adjusted R-squared: {joint['maximum_adjusted_r2']:.3f} (gate <0.85: {'PASS' if joint['maximum_gate_pass'] else 'FAIL'}).",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Path panel SHA-256: `{result['hashes']['path_panel_sha256']}`",
        f"- Volatility panel SHA-256: `{result['hashes']['volatility_panel_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel = load_bound_inputs(spec)
    cell_support = _assert_cell_support(panel, spec)
    pairwise = _pairwise_geometry(panel, spec)
    joint = _joint_geometry(panel, spec)
    distinct = bool(
        all(item["pairwise_distinct"] for item in pairwise.values())
        and joint["median_gate_pass"] and joint["maximum_gate_pass"]
    )
    status = "COMPLETE_DISTINCT_PATH_COORDINATE" if distinct else "COMPLETE_PATH_COMPRESSED_INTO_VOLATILITY_FAMILY"

    output = panel.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "population": {
            "rows": int(len(panel)),
            "groups": int(panel.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(panel["trade_date"].min().date()),
            "last_date": str(panel["trade_date"].max().date()),
        },
        "pairwise_geometry": pairwise,
        "joint_rank_reconstruction": joint,
        "cell_support": cell_support,
        "gates": {"distinct_path_coordinate": distinct},
        "raw_minute_rows_read": 0,
        "failed_representation_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "cy011_read": False,
        "mechanism_claim": "DISTINCT_VOLATILITY_PATH_COORDINATE" if distinct else "VOLATILITY_FAMILY_MANIFESTATION",
        "usefulness_claim": "NONE",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "path_panel_sha256": spec["inputs"]["path_panel"]["sha256"],
            "path_result_sha256": spec["inputs"]["path_result"]["sha256"],
            "volatility_panel_sha256": spec["inputs"]["volatility_panel"]["sha256"],
            "volatility_result_sha256": spec["inputs"]["volatility_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "pairwise_distinct": {
            key: value["pairwise_distinct"] for key, value in completed["pairwise_geometry"].items()
        },
        "joint_rank_reconstruction": completed["joint_rank_reconstruction"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
