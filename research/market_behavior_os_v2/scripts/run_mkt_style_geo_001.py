#!/usr/bin/env python3
"""Estimate frozen external geometry of circulating-size market states."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-GEO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-STYLE-GEO-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-GEO-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-GEO-001_geometry.md"
EXPECTED_SPEC_SHA256 = "2bf960c60d5fffcb98bb9442c2d05eb91859b91002baf69eab69b2b98bb6d7c8"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")


class StyleGeometryError(RuntimeError):
    """Fail-closed MKT-STYLE-GEO-001 error."""


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
        raise StyleGeometryError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_EXTERNAL_GEOMETRY_ESTIMATION":
        raise StyleGeometryError("spec is not frozen before geometry")
    if list(spec["role_fields"]) != spec["required_style_roles"]:
        raise StyleGeometryError("required role order mismatch")
    if set(spec["role_fields"]) != set(spec["control_fields"]):
        raise StyleGeometryError("role/control mapping mismatch")
    if any(len(controls) != 3 for controls in spec["control_fields"].values()):
        raise StyleGeometryError("every role requires exactly three controls")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, dict[str, Path]]:
    paths: dict[str, dict[str, Path]] = {}
    for source, entries in spec["inputs"].items():
        paths[source] = {}
        for kind in ("panel", "result"):
            path = ROOT / entries[kind]["path"]
            if sha256_file(path) != entries[kind]["sha256"]:
                raise StyleGeometryError(f"{source} {kind} identity mismatch")
            paths[source][kind] = path
    return paths


def _validate_source_results(
    spec: dict[str, Any], paths: dict[str, dict[str, Path]]
) -> dict[str, Any]:
    results = {
        source: json.loads(entries["result"].read_text(encoding="utf-8"))
        for source, entries in paths.items()
    }
    if results["style"]["compression"]["accepted_roles"] != spec["required_style_roles"]:
        raise StyleGeometryError("style accepted-role identity mismatch")
    expected_minimal = {
        "breadth": ["new_high_low", "leadership_concentration"],
        "correlation_liquidity": [
            "co_movement", "directional_synchronization", "liquidity_activity",
            "turnover_level", "liquidity_concentration",
        ],
        "volatility": [
            "realized_volatility", "intraday_range", "volatility_concentration",
            "volatility_change",
        ],
        "risk_appetite": [
            "central_direction", "upside_extreme_participation", "downside_extreme_participation",
        ],
    }
    for source, expected in expected_minimal.items():
        if results[source]["minimal_panel"]["accepted_roles"] != expected:
            raise StyleGeometryError(f"{source} accepted-role identity mismatch")
    expected_industry = [
        "industry_return_dispersion_1d",
        "winner_industry_diffusion20",
        "industry_rank_rotation20",
        "stock_industry_rs_tail_balance20",
        "stock_industry_rs_concentration20",
    ]
    if results["industry_geometry"]["compression"]["distinct_engine_coordinates"] != expected_industry:
        raise StyleGeometryError("industry direct-coordinate identity mismatch")
    for source, result in results.items():
        if result.get("usefulness_claim") != "NONE":
            raise StyleGeometryError(f"{source} usefulness boundary changed")
    return results


def _style_field(raw: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "__pit_3y_pct",
        "relative_to_all": "__relative_to_all",
        "relative_rank": "__relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def _control_field(raw: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def _fields_by_source(spec: dict[str, Any]) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {source: [] for source in spec["inputs"]}
    for raw in spec["role_fields"].values():
        fields["style"].extend(_style_field(raw, coordinate) for coordinate in COORDINATES)
    for raw, source in spec["field_sources"].items():
        fields[source].extend(_control_field(raw, coordinate) for coordinate in COORDINATES)
    return {source: list(dict.fromkeys(items)) for source, items in fields.items()}


def _audit_source(
    source: str, frame: pd.DataFrame, result: dict[str, Any]
) -> dict[str, Any]:
    if frame.duplicated(KEYS).any():
        raise StyleGeometryError(f"{source} duplicate keys")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    expected_rows = int(result["population"]["rows"])
    if len(frame) != expected_rows:
        raise StyleGeometryError(f"{source} source row population mismatch")
    counts = frame.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8:
        raise StyleGeometryError(f"{source} group identity mismatch")
    if source == "industry_geometry":
        observed_time = pd.to_datetime(frame["geometry_decision_at"], errors="raise", utc=True)
    else:
        available = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
        decision = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
        if (available > decision).any():
            raise StyleGeometryError(f"{source} time travel")
        observed_time = available
    local = observed_time.dt.tz_convert("Asia/Shanghai")
    if not (local.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise StyleGeometryError(f"{source} availability is not exact 15:00")
    if not (local.dt.date == frame["trade_date"].dt.date).all():
        raise StyleGeometryError(f"{source} date/availability mismatch")
    return {
        "rows": int(len(frame)),
        "groups": int(len(counts)),
        "first_date": str(frame["trade_date"].min().date()),
        "last_date": str(frame["trade_date"].max().date()),
    }


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = _input_paths(spec)
    results = _validate_source_results(spec, paths)
    fields_by_source = _fields_by_source(spec)
    order = ["industry_geometry", "style", "breadth", "correlation_liquidity", "volatility", "risk_appetite"]
    merged: pd.DataFrame | None = None
    audits: dict[str, Any] = {}
    for source in order:
        time_fields = ["geometry_decision_at"] if source == "industry_geometry" else ["decision_at", "available_at"]
        frame = pd.read_csv(
            paths[source]["panel"], usecols=[*KEYS, *time_fields, *fields_by_source[source]]
        )
        audits[source] = _audit_source(source, frame, results[source])
        values = frame[[*KEYS, *fields_by_source[source]]].copy()
        if merged is None:
            merged = values
        else:
            before = len(merged)
            merged = merged.merge(values, on=KEYS, how="left", validate="one_to_one")
            if len(merged) != before:
                raise StyleGeometryError(f"{source} merge row identity mismatch")
    if merged is None:
        raise StyleGeometryError("no sources loaded")
    if merged[_fields_by_source(spec)["style"]].isna().all(axis=None):
        raise StyleGeometryError("style fields missing after merge")
    merged["geometry_decision_at"] = merged["trade_date"].dt.strftime("%Y-%m-%dT15:00:00+08:00")
    return merged.sort_values(KEYS).reset_index(drop=True), audits


def _role_fields(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        role: {coordinate: _style_field(raw, coordinate) for coordinate in COORDINATES}
        for role, raw in spec["role_fields"].items()
    }


def _control_fields(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        raw: {coordinate: _control_field(raw, coordinate) for coordinate in COORDINATES}
        for raw in spec["field_sources"]
    }


def _coordinate_frame(panel: pd.DataFrame, spec: dict[str, Any], coordinate: str) -> pd.DataFrame:
    work = panel.loc[panel["trade_date"].dt.year.isin(spec["population"]["eligible_years"])].copy()
    if coordinate == "relative_to_all":
        work = work.loc[work["market_view"] != "ALL_A"]
    return work


def complete_support_audit(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    roles: dict[str, dict[str, str]],
    controls: dict[str, dict[str, str]],
) -> dict[str, Any]:
    minimum = spec["gates"]["minimum_group_year_observations"]
    audit: dict[str, Any] = {}
    for role in spec["required_style_roles"]:
        role_audit: dict[str, Any] = {}
        for coordinate in COORDINATES:
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
                nondegenerate = {field: bool(clean[field].nunique() > 1) for field in required}
                key = f"{view}:{denominator}:{year}"
                cells[key] = {"observations": int(len(clean)), "nondegenerate": nondegenerate}
                if len(clean) < minimum or not all(nondegenerate.values()):
                    raise StyleGeometryError(f"support failed: {role}:{coordinate}:{key}")
            role_audit[coordinate] = cells
        audit[role] = role_audit
    return audit


def _spearman(frame: pd.DataFrame, left: str, right: str) -> float:
    clean = frame[[left, right]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean[left].nunique() < 2 or clean[right].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def adjusted_rank_r2(frame: pd.DataFrame, target: str, control_fields: list[str]) -> float:
    clean = frame[[target, *control_fields]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(control_fields) + 2:
        return float("nan")
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    response = ranked[:, 0]
    design = np.column_stack([np.ones(len(ranked), dtype=float), ranked[:, 1:]])
    coefficients = np.linalg.lstsq(design, response, rcond=None)[0]
    residual = response - design @ coefficients
    centered = response - response.mean()
    total_ss = float(centered @ centered)
    if total_ss <= 0:
        return float("nan")
    r2 = 1.0 - float(residual @ residual) / total_ss
    n = len(clean)
    p = len(control_fields)
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _groups(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in frame.groupby(["market_view", "denominator"], sort=True)
    ]


def estimate_geometry(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    roles: dict[str, dict[str, str]],
    controls: dict[str, dict[str, str]],
) -> dict[str, Any]:
    gates = spec["gates"]
    output: dict[str, Any] = {}
    for role in spec["required_style_roles"]:
        pairwise: dict[str, Any] = {}
        joint: dict[str, Any] = {}
        for coordinate in COORDINATES:
            work = _coordinate_frame(panel, spec, coordinate)
            target = roles[role][coordinate]
            control_names = spec["control_fields"][role]
            coordinate_pairs: dict[str, Any] = {}
            for control_name in control_names:
                control = controls[control_name][coordinate]
                by_group = {
                    name: _spearman(group, target, control)
                    for name, group in _groups(work)
                }
                values = np.asarray(list(by_group.values()), dtype=float)
                if not np.isfinite(values).all():
                    raise StyleGeometryError(f"pairwise estimate failed: {role}:{control_name}:{coordinate}")
                median = float(np.median(np.abs(values)))
                coordinate_pairs[control_name] = {
                    "by_group": by_group,
                    "median_absolute_spearman": median,
                    "maximum_absolute_spearman": float(np.max(np.abs(values))),
                    "gate_pass": bool(median < gates["pairwise_external_redundancy_absolute_spearman"]),
                }
            pairwise[coordinate] = coordinate_pairs
            joint_controls = [controls[name][coordinate] for name in control_names]
            by_group_r2 = {
                name: adjusted_rank_r2(group, target, joint_controls)
                for name, group in _groups(work)
            }
            r2_values = np.asarray(list(by_group_r2.values()), dtype=float)
            if not np.isfinite(r2_values).all():
                raise StyleGeometryError(f"joint estimate failed: {role}:{coordinate}")
            median_r2 = float(np.median(r2_values))
            maximum_r2 = float(np.max(r2_values))
            joint[coordinate] = {
                "by_group": by_group_r2,
                "median_adjusted_rank_r2": median_r2,
                "maximum_adjusted_rank_r2": maximum_r2,
                "gate_pass": bool(
                    median_r2 < gates["joint_rank_reconstruction_median_adjusted_r2_maximum"]
                    and maximum_r2 < gates["joint_rank_reconstruction_maximum_adjusted_r2"]
                ),
            }
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
            "fixed_controls": spec["control_fields"][role],
            "pairwise": pairwise,
            "joint": joint,
            "pairwise_gate_pass": pairwise_pass,
            "joint_gate_pass": joint_pass,
            "classification": classification,
        }
    return output


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-STYLE-GEO-001 circulating-size external geometry",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Common population: {result['population']['rows']:,} rows in {result['population']['groups']} groups.",
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
        joint_median = max(value["median_adjusted_rank_r2"] for value in item["joint"].values())
        joint_max = max(value["maximum_adjusted_rank_r2"] for value in item["joint"].values())
        lines.append(
            f"| `{role}` | {pairwise_max:.3f} | {joint_median:.3f} | {joint_max:.3f} | "
            f"{item['classification']} |"
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
    roles = _role_fields(spec)
    controls = _control_fields(spec)
    support = complete_support_audit(panel, spec, roles, controls)
    diagnostics = estimate_geometry(panel, spec, roles, controls)
    distinct = [role for role in spec["required_style_roles"] if diagnostics[role]["classification"] == "DISTINCT_ENGINE_COORDINATE"]
    pairwise = [role for role in spec["required_style_roles"] if diagnostics[role]["classification"] == "PAIRWISE_REDUNDANT"]
    joint = [role for role in spec["required_style_roles"] if diagnostics[role]["classification"] == "JOINTLY_RECONSTRUCTABLE"]
    output_fields = list(dict.fromkeys([
        *[field for mapping in roles.values() for field in mapping.values()],
        *[field for mapping in controls.values() for field in mapping.values()],
    ]))
    output = panel[[*KEYS, "geometry_decision_at", *output_fields]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(distinct)}_OF_{len(spec['required_style_roles'])}_DISTINCT_ENGINE_COORDINATES",
        "usefulness_claim": "NONE",
        "future_values_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_controls_or_style_roles_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
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
    print(json.dumps({
        "status": completed["status"],
        "compression": completed["compression"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
