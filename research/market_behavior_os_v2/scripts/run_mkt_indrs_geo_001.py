#!/usr/bin/env python3
"""Outcome-blind external geometry of frozen industry/relative-strength roles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-GEO-002_spec.json"
PARENT_SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-GEO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-INDRS-GEO-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-INDRS-GEO-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-INDRS-GEO-002_geometry.md"
EXPECTED_SPEC_SHA256 = "7b91844c094003e8fe341942cba3bed9b43a5a393b004d4cb08960dc226fa46e"
EXPECTED_PARENT_SPEC_SHA256 = "33b0f114becea9d2677e3e38fd51f45e1433279c8058a26a94a435ff78ea276e"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")


class IndustryGeometryError(RuntimeError):
    """Fail-closed MKT-INDRS-GEO-002 error."""


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IndustryGeometryError("spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if sha256_file(PARENT_SPEC_PATH) != EXPECTED_PARENT_SPEC_SHA256:
        raise IndustryGeometryError("parent scientific design identity mismatch")
    if control["inherits_scientific_design_sha256"] != EXPECTED_PARENT_SPEC_SHA256:
        raise IndustryGeometryError("control parent identity mismatch")
    spec = json.loads(PARENT_SPEC_PATH.read_text(encoding="utf-8"))
    spec["experiment_id"] = control["experiment_id"]
    spec["status"] = control["status"]
    spec["outputs"] = control["outputs"]
    spec["control_coordinate_years"] = control["only_semantic_correction"]["control_coordinate_years"]
    spec["joint_coordinate_years"] = control["only_semantic_correction"]["joint_coordinate_years"]
    if spec["status"] != "FROZEN_BEFORE_GEOMETRY_RESULT":
        raise IndustryGeometryError("spec is not frozen before geometry")
    if set(spec["targets"]) != set(spec["role_control_sets"]):
        raise IndustryGeometryError("target/control-set identity mismatch")
    if any(len(controls) > 3 or not controls for controls in spec["role_control_sets"].values()):
        raise IndustryGeometryError("every target requires one to three fixed controls")
    if any(control not in spec["controls"] for controls in spec["role_control_sets"].values() for control in controls):
        raise IndustryGeometryError("unknown fixed control")
    return spec


def _field(raw: str, coordinate: str) -> str:
    suffixes = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }
    return raw + suffixes[coordinate]


def _input_paths(spec: dict[str, Any]) -> dict[str, dict[str, Path]]:
    output: dict[str, dict[str, Path]] = {}
    for source, entry in spec["inputs"].items():
        panel = ROOT / entry["panel_path"]
        result = ROOT / entry["result_path"]
        if sha256_file(panel) != entry["panel_sha256"]:
            raise IndustryGeometryError(f"{source} panel identity mismatch")
        if sha256_file(result) != entry["result_sha256"]:
            raise IndustryGeometryError(f"{source} result identity mismatch")
        output[source] = {"panel": panel, "result": result}
    return output


def _validate_source_results(spec: dict[str, Any], paths: dict[str, dict[str, Path]]) -> None:
    for source, expected in spec["source_role_expectations"].items():
        result = json.loads(paths[source]["result"].read_text(encoding="utf-8"))
        observed = result.get("minimal_panel", {}).get("accepted_roles")
        if observed != expected:
            raise IndustryGeometryError(f"{source} accepted-role identity mismatch")
        if result.get("usefulness_claim") != "NONE":
            raise IndustryGeometryError(f"{source} usefulness boundary changed")


def _source_raw_fields(spec: dict[str, Any]) -> dict[str, list[str]]:
    fields = {source: [] for source in spec["inputs"]}
    fields["industry"].extend(spec["targets"].values())
    for control in spec["controls"].values():
        fields[control["source"]].append(control["raw"])
    return {source: list(dict.fromkeys(items)) for source, items in fields.items()}


def _audit_source_frame(
    source: str, frame: pd.DataFrame, spec: dict[str, Any], reference_keys: pd.DataFrame | None
) -> pd.DataFrame:
    population = spec["population"]
    if len(frame) != population["expected_rows"] or frame.duplicated(KEYS).any():
        raise IndustryGeometryError(f"{source} row/key audit failed")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if str(frame["trade_date"].min().date()) != population["date_start"]:
        raise IndustryGeometryError(f"{source} start date mismatch")
    if str(frame["trade_date"].max().date()) != population["date_end"]:
        raise IndustryGeometryError(f"{source} end date mismatch")
    available = pd.to_datetime(frame["available_at"], errors="raise", utc=True).dt.tz_convert("Asia/Shanghai")
    decision = pd.to_datetime(frame["decision_at"], errors="raise", utc=True).dt.tz_convert("Asia/Shanghai")
    if (available > decision).any():
        raise IndustryGeometryError(f"{source} time travel")
    if not (available.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise IndustryGeometryError(f"{source} availability is not exact 15:00")
    if not (available.dt.date == frame["trade_date"].dt.date).all():
        raise IndustryGeometryError(f"{source} availability date mismatch")
    counts = frame.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != spec["gates"]["exact_groups"] or not (
        counts == population["expected_rows_per_group"]
    ).all():
        raise IndustryGeometryError(f"{source} group population mismatch")
    if set(frame["market_view"]) != set(population["views"]):
        raise IndustryGeometryError(f"{source} view identity mismatch")
    if set(frame["denominator"]) != set(population["denominators"]):
        raise IndustryGeometryError(f"{source} denominator identity mismatch")
    ordered_keys = frame[KEYS].sort_values(KEYS).reset_index(drop=True)
    if reference_keys is not None and not ordered_keys.equals(reference_keys):
        raise IndustryGeometryError(f"{source} key-set mismatch")
    return ordered_keys


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = _input_paths(spec)
    _validate_source_results(spec, paths)
    raw_fields = _source_raw_fields(spec)
    merged: pd.DataFrame | None = None
    reference_keys: pd.DataFrame | None = None
    audits: dict[str, Any] = {}
    for source in spec["inputs"]:
        coordinate_fields = [
            _field(raw, coordinate)
            for raw in raw_fields[source]
            for coordinate in COORDINATES
        ]
        columns = [*KEYS, "decision_at", "available_at", *coordinate_fields]
        frame = pd.read_csv(paths[source]["panel"], usecols=columns)
        observed_keys = _audit_source_frame(source, frame, spec, reference_keys)
        if reference_keys is None:
            reference_keys = observed_keys
        audits[source] = {
            "rows": int(len(frame)),
            "first_date": str(frame["trade_date"].min().date()),
            "last_date": str(frame["trade_date"].max().date()),
            "panel_sha256": spec["inputs"][source]["panel_sha256"],
            "result_sha256": spec["inputs"][source]["result_sha256"],
        }
        values = frame[[*KEYS, *coordinate_fields]].copy()
        if merged is None:
            merged = values
        else:
            merged = merged.merge(values, on=KEYS, how="outer", indicator=True, validate="one_to_one")
            if not (merged["_merge"] == "both").all():
                raise IndustryGeometryError(f"{source} merge population mismatch")
            merged = merged.drop(columns="_merge")
    if merged is None:
        raise IndustryGeometryError("no bound sources")
    merged["geometry_decision_at"] = merged["trade_date"].dt.strftime("%Y-%m-%dT15:00:00+08:00")
    return merged.sort_values(KEYS).reset_index(drop=True), audits


def _coordinate_fields(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    targets = {
        role: {coordinate: _field(raw, coordinate) for coordinate in COORDINATES}
        for role, raw in spec["targets"].items()
    }
    controls = {
        name: {coordinate: _field(item["raw"], coordinate) for coordinate in COORDINATES}
        for name, item in spec["controls"].items()
    }
    return {"targets": targets, "controls": controls}


def _coverage_and_cells(
    panel: pd.DataFrame, spec: dict[str, Any], fields: dict[str, dict[str, str]]
) -> tuple[dict[str, Any], dict[str, int]]:
    minimum_coverage = spec["gates"]["expected_coordinate_coverage"]
    minimum_cell = spec["gates"]["group_year_minimum_observations"]
    coverage: dict[str, Any] = {}
    cell_support: dict[str, int] = {}
    work = panel.assign(year=panel["trade_date"].dt.year)
    named_fields = [
        ("target", name, mapping) for name, mapping in fields["targets"].items()
    ] + [
        ("control", name, mapping) for name, mapping in fields["controls"].items()
    ]
    for kind, name, mapping in named_fields:
        for coordinate in COORDINATES:
            coordinate_years = _cell_years(spec, kind, name, coordinate)
            coordinate_panel = work.loc[work["year"].isin(coordinate_years)].copy()
            if coordinate == "relative_to_all":
                coordinate_panel = coordinate_panel.loc[coordinate_panel["market_view"] != "ALL_A"]
            field = mapping[coordinate]
            values = pd.to_numeric(coordinate_panel[field], errors="coerce").replace([np.inf, -np.inf], np.nan)
            expected = len(values)
            observed = int(values.notna().sum())
            ratio = float(observed / expected) if expected else float("nan")
            coverage[f"{coordinate}:{field}"] = {"observed": observed, "expected": expected, "ratio": ratio}
            if not np.isfinite(ratio) or ratio < minimum_coverage:
                raise IndustryGeometryError(f"coordinate coverage failed: {coordinate}:{field}")
            if coordinate.startswith("relative"):
                grouped_cells = coordinate_panel.groupby(["denominator", "year"], sort=True)
                required = minimum_cell * (3 if coordinate == "relative_to_all" else 4)
            else:
                grouped_cells = coordinate_panel.groupby(["market_view", "denominator", "year"], sort=True)
                required = minimum_cell
            for group_key, group in grouped_cells:
                finite = pd.to_numeric(group[field], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
                key = f"{coordinate}:{':'.join(str(item) for item in group_key)}:{field}"
                cell_support[key] = int(len(finite))
                if len(finite) < required or finite.nunique() < 2:
                    raise IndustryGeometryError(f"coordinate cell support failed: {key}")
    return coverage, cell_support


def _default_cell_years(spec: dict[str, Any], coordinate: str) -> list[int]:
    if coordinate == "pit":
        return spec["population"]["pit_cell_and_geometry_years"]
    if coordinate.startswith("relative"):
        return spec["population"]["relative_cell_and_geometry_years"]
    return spec["population"]["raw_cell_years"]


def _cell_years(
    spec: dict[str, Any], kind: str, name: str, coordinate: str
) -> list[int]:
    if kind == "control" and name in spec["control_coordinate_years"]:
        return spec["control_coordinate_years"][name][coordinate]
    return _default_cell_years(spec, coordinate)


def _spearman(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    clean = frame[[target, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(controls) + 2:
        return float("nan")
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    y = ranked[:, 0]
    x = np.column_stack([np.ones(len(ranked), dtype=float), ranked[:, 1:]])
    coefficients, _, _, _ = np.linalg.lstsq(x, y, rcond=None)
    residual = y - x @ coefficients
    total = y - y.mean()
    total_ss = float(total @ total)
    if total_ss <= 0.0:
        return float("nan")
    r2 = 1.0 - float(residual @ residual) / total_ss
    n = len(clean)
    p = len(controls)
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _analysis_groups(
    panel: pd.DataFrame, spec: dict[str, Any], coordinate: str, years: list[int] | None = None
) -> list[tuple[str, pd.DataFrame]]:
    work = panel
    if years is None and coordinate == "pit":
        years = spec["population"]["pit_cell_and_geometry_years"]
    elif years is None and coordinate.startswith("relative"):
        years = spec["population"]["relative_cell_and_geometry_years"]
    if years is not None:
        work = work.loc[work["trade_date"].dt.year.isin(years)]
    if coordinate == "relative_to_all":
        work = work.loc[work["market_view"] != "ALL_A"]
    if coordinate.startswith("relative"):
        return [
            (str(denominator), group)
            for denominator, group in work.groupby("denominator", sort=True)
        ]
    return [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in work.groupby(["market_view", "denominator"], sort=True)
    ]


def _geometry(
    panel: pd.DataFrame, spec: dict[str, Any], fields: dict[str, dict[str, str]]
) -> dict[str, Any]:
    pair_threshold = spec["gates"]["pairwise_median_absolute_spearman_strictly_below"]
    joint_median_threshold = spec["gates"]["joint_rank_adjusted_r2_median_strictly_below"]
    joint_max_threshold = spec["gates"]["joint_rank_adjusted_r2_maximum_strictly_below"]
    diagnostics: dict[str, Any] = {}
    for role, control_names in spec["role_control_sets"].items():
        target_fields = fields["targets"][role]
        pairwise: dict[str, Any] = {}
        for control_name in control_names:
            control_fields = fields["controls"][control_name]
            coordinate_output: dict[str, Any] = {}
            for coordinate in COORDINATES:
                control_years = spec["control_coordinate_years"].get(control_name, {}).get(coordinate)
                pairs = {
                    group_name: _spearman(group[target_fields[coordinate]], group[control_fields[coordinate]])
                    for group_name, group in _analysis_groups(panel, spec, coordinate, control_years)
                }
                values = np.asarray(list(pairs.values()), dtype=float)
                if not np.isfinite(values).all():
                    raise IndustryGeometryError(f"nonfinite pairwise geometry: {role}:{control_name}:{coordinate}")
                median = float(np.median(np.abs(values)))
                coordinate_output[coordinate] = {
                    "by_group": pairs,
                    "median_absolute_spearman": median,
                    "maximum_absolute_spearman": float(np.max(np.abs(values))),
                    "gate_pass": bool(median < pair_threshold),
                }
            pairwise[control_name] = coordinate_output

        joint: dict[str, Any] = {}
        for coordinate in COORDINATES:
            control_fields = [fields["controls"][name][coordinate] for name in control_names]
            joint_years = spec["joint_coordinate_years"].get(role, {}).get(coordinate)
            by_group = {
                group_name: adjusted_rank_r2(group, target_fields[coordinate], control_fields)
                for group_name, group in _analysis_groups(panel, spec, coordinate, joint_years)
            }
            values = np.asarray(list(by_group.values()), dtype=float)
            if not np.isfinite(values).all():
                raise IndustryGeometryError(f"nonfinite joint geometry: {role}:{coordinate}")
            median = float(np.median(values))
            maximum = float(np.max(values))
            joint[coordinate] = {
                "by_group": by_group,
                "median_adjusted_rank_r2": median,
                "maximum_adjusted_rank_r2": maximum,
                "gate_pass": bool(median < joint_median_threshold and maximum < joint_max_threshold),
            }

        pairwise_pass = all(
            item["gate_pass"]
            for control in pairwise.values()
            for item in control.values()
        )
        joint_pass = all(item["gate_pass"] for item in joint.values())
        classification = (
            "DISTINCT_ENGINE_COORDINATE"
            if pairwise_pass and joint_pass
            else "PAIRWISE_REDUNDANT"
            if not pairwise_pass
            else "JOINTLY_RECONSTRUCTABLE"
        )
        diagnostics[role] = {
            "target_fields": target_fields,
            "fixed_controls": control_names,
            "pairwise": pairwise,
            "joint": joint,
            "pairwise_gate_pass": pairwise_pass,
            "joint_gate_pass": joint_pass,
            "classification": classification,
        }
    return diagnostics


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-INDRS-GEO-002 industry/relative-strength external geometry",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Common population: {result['population']['rows']:,} rows, {result['population']['groups']} groups.",
        "- Future values, market returns, strategy outcomes, failed industry roles, failed MA fields, and CY-011 read: **none**.",
        "- Geometry is contemporaneous redundancy evidence, not temporal meaning, habitat, prediction, or a strategy.",
        "",
        "## Role geometry",
        "",
        "| Role | Largest pairwise median abs rho | Largest joint median adj R2 | Largest joint max adj R2 | Classification |",
        "|---|---:|---:|---:|---|",
    ]
    for role in spec["targets"]:
        diagnostic = result["role_diagnostics"][role]
        pairwise_max = max(
            coordinate["median_absolute_spearman"]
            for control in diagnostic["pairwise"].values()
            for coordinate in control.values()
        )
        joint_median = max(item["median_adjusted_rank_r2"] for item in diagnostic["joint"].values())
        joint_max = max(item["maximum_adjusted_rank_r2"] for item in diagnostic["joint"].values())
        lines.append(
            f"| `{role}` | {pairwise_max:.3f} | {joint_median:.3f} | {joint_max:.3f} | "
            f"{diagnostic['classification']} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel, input_audit = load_bound_inputs(spec)
    fields = _coordinate_fields(spec)
    coverage, cell_support = _coverage_and_cells(panel, spec, fields)
    diagnostics = _geometry(panel, spec, fields)
    distinct = [role for role in spec["targets"] if diagnostics[role]["classification"] == "DISTINCT_ENGINE_COORDINATE"]
    pairwise_redundant = [role for role in spec["targets"] if diagnostics[role]["classification"] == "PAIRWISE_REDUNDANT"]
    jointly_reconstructable = [role for role in spec["targets"] if diagnostics[role]["classification"] == "JOINTLY_RECONSTRUCTABLE"]

    output_fields = list(dict.fromkeys(
        field
        for mapping_type in ("targets", "controls")
        for mapping in fields[mapping_type].values()
        for field in mapping.values()
    ))
    output = panel[[*KEYS, "geometry_decision_at", *output_fields]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(distinct)}_OF_{len(spec['targets'])}_DISTINCT_ENGINE_COORDINATES",
        "usefulness_claim": "NONE",
        "future_values_read": [],
        "market_return_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_industry_roles_read": [],
        "failed_ma_industry_fields_read": [],
        "cy011_read": False,
        "input_audit": input_audit,
        "population": {
            "rows": int(len(output)),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
        },
        "coordinate_coverage": coverage,
        "minimum_cell_observations": int(min(cell_support.values())),
        "role_diagnostics": diagnostics,
        "compression": {
            "distinct_engine_coordinates": distinct,
            "pairwise_redundant": pairwise_redundant,
            "jointly_reconstructable": jointly_reconstructable,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "bound_input_sha256": {
                source: {
                    "panel": entry["panel_sha256"],
                    "result": entry["result_sha256"],
                }
                for source, entry in spec["inputs"].items()
            },
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result, spec), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "compression": completed["compression"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
