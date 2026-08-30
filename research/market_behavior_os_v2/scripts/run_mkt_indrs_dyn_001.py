#!/usr/bin/env python3
"""Construct frozen outcome-blind industry leadership temporal dynamics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-INDRS-DYN-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-INDRS-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-INDRS-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "b1266eed922e974b08b4a4a29bc01e574a09f0e2b7ecb0fe044210c39c3f1fdf"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")
BLOCK_NAMES = ("discovery", "confirmation_untouched_before_specification")


class IndustryDynamicsError(RuntimeError):
    """Fail-closed MKT-INDRS-DYN-001 error."""


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
        raise IndustryDynamicsError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_STATE_CONSTRUCTION":
        raise IndustryDynamicsError("spec is not frozen before future-state construction")
    if set(spec["edges"]) != {
        "rotation_persistence", "diffusion_to_rotation", "rotation_to_diffusion_change"
    }:
        raise IndustryDynamicsError("edge identity mismatch")
    return spec


def _field(raw: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise IndustryDynamicsError(f"{name} identity mismatch")
        output[name] = path
    return output


def _validate_geometry_result(spec: dict[str, Any], path: Path) -> None:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["compression"]["distinct_engine_coordinates"] != spec["required_direct_engine_coordinates"]:
        raise IndustryDynamicsError("direct engine-coordinate identity mismatch")
    if result["usefulness_claim"] != "NONE":
        raise IndustryDynamicsError("geometry usefulness boundary changed")
    if result["future_values_read"] or result["strategy_or_outcome_fields_read"]:
        raise IndustryDynamicsError("geometry source boundary changed")


def _allowed_source_fields(spec: dict[str, Any]) -> list[str]:
    raw_fields = list(spec["fields"].values())
    return list(dict.fromkeys(
        field
        for raw in raw_fields
        for field in (_field(raw, coordinate) for coordinate in COORDINATES)
    ))


def load_bound_input(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_geometry_result(spec, paths["geometry_result"])
    fields = _allowed_source_fields(spec)
    panel = pd.read_csv(paths["geometry_panel"], usecols=[*KEYS, "geometry_decision_at", *fields])
    population = spec["population"]
    if len(panel) != population["expected_rows"] or panel.duplicated(KEYS).any():
        raise IndustryDynamicsError("source row/key identity mismatch")
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    if str(panel["trade_date"].min().date()) != population["date_start"]:
        raise IndustryDynamicsError("source start changed")
    if str(panel["trade_date"].max().date()) != population["date_end"]:
        raise IndustryDynamicsError("source end changed")
    decision = pd.to_datetime(panel["geometry_decision_at"], errors="raise", utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    if not (decision.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise IndustryDynamicsError("predictor availability is not exact 15:00")
    if not (decision.dt.date == panel["trade_date"].dt.date).all():
        raise IndustryDynamicsError("predictor date/availability mismatch")
    counts = panel.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not (counts == population["expected_rows_per_group"]).all():
        raise IndustryDynamicsError("source group population mismatch")
    if set(panel["market_view"]) != set(population["views"]):
        raise IndustryDynamicsError("source view identity mismatch")
    if set(panel["denominator"]) != set(population["denominators"]):
        raise IndustryDynamicsError("source denominator identity mismatch")
    return panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)


def _response_name(response: str, coordinate: str) -> str:
    return f"{response}__{coordinate}"


def construct_future_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    shift = spec["population"]["future_shift_sessions"]
    out = panel.copy()
    grouped = out.groupby(["market_view", "denominator"], sort=False)
    out["future_trade_date"] = grouped["trade_date"].shift(-shift)
    out["response_available_at"] = out["future_trade_date"].dt.strftime("%Y-%m-%dT15:00:00+08:00")
    rotation_raw = spec["fields"]["rank_rotation"]
    diffusion_raw = spec["fields"]["winner_diffusion"]
    for coordinate in COORDINATES:
        rotation = _field(rotation_raw, coordinate)
        diffusion = _field(diffusion_raw, coordinate)
        out[_response_name("next_block_rank_rotation5", coordinate)] = grouped[rotation].shift(-shift)
        out[_response_name("future_winner_diffusion_change5", coordinate)] = (
            grouped[diffusion].shift(-shift) - out[diffusion]
        )
    expected_missing = shift * 8
    if int(out["future_trade_date"].isna().sum()) != expected_missing:
        raise IndustryDynamicsError("future tail count mismatch")
    predictor_time = pd.to_datetime(out["geometry_decision_at"], errors="raise", utc=True)
    response_time = pd.to_datetime(out["response_available_at"], errors="coerce", utc=True)
    if not (response_time.dropna() > predictor_time.loc[response_time.notna()]).all():
        raise IndustryDynamicsError("response is not strictly later than predictor")
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        future_dates = group["trade_date"].shift(-shift)
        if not group["future_trade_date"].equals(future_dates):
            raise IndustryDynamicsError("future date is not exact five-row shift")
    return out.sort_values(KEYS).reset_index(drop=True)


def _block_frame(panel: pd.DataFrame, spec: dict[str, Any], block_name: str) -> pd.DataFrame:
    block = spec["temporal_blocks"][block_name]
    start = pd.Timestamp(block["start"])
    end = pd.Timestamp(block["end"])
    return panel.loc[
        panel["trade_date"].between(start, end)
        & panel["future_trade_date"].between(start, end)
    ].copy()


def partial_rank_correlation(
    frame: pd.DataFrame, predictor: str, response: str, controls: list[str]
) -> tuple[float, int]:
    clean = frame[[predictor, response, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(controls) + 3:
        return float("nan"), int(len(clean))
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(ranked), dtype=float), ranked[:, 2:]])
    predictor_residual = ranked[:, 0] - x @ np.linalg.lstsq(x, ranked[:, 0], rcond=None)[0]
    response_residual = ranked[:, 1] - x @ np.linalg.lstsq(x, ranked[:, 1], rcond=None)[0]
    if np.std(predictor_residual) == 0.0 or np.std(response_residual) == 0.0:
        return float("nan"), int(len(clean))
    return float(np.corrcoef(predictor_residual, response_residual)[0, 1]), int(len(clean))


def _phase_zero(frame: pd.DataFrame, required: list[str]) -> pd.DataFrame:
    valid = frame.dropna(subset=required).sort_values(KEYS).copy()
    ordinal = valid.groupby(["market_view", "denominator"], sort=False).cumcount()
    return valid.loc[ordinal % 5 == 0].copy()


def _analysis_groups(
    frame: pd.DataFrame, coordinate: str
) -> list[tuple[str, pd.DataFrame]]:
    work = frame
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


def _edge_fields(spec: dict[str, Any], edge_name: str, coordinate: str) -> tuple[str, str, list[str]]:
    edge = spec["edges"][edge_name]
    predictor = _field(spec["fields"][edge["predictor"]], coordinate)
    response = _response_name(edge["response"], coordinate)
    controls = [_field(spec["fields"][name], coordinate) for name in edge["controls"]]
    return predictor, response, controls


def _minimum_support(spec: dict[str, Any], coordinate: str) -> int:
    if coordinate == "raw":
        return spec["gates"]["raw_group_block_minimum_observations"]
    if coordinate == "pit":
        return spec["gates"]["pit_group_block_minimum_observations"]
    if coordinate == "relative_to_all":
        return spec["gates"]["relative_to_all_denominator_block_minimum_observations"]
    return spec["gates"]["relative_rank_denominator_block_minimum_observations"]


def _coordinate_block_estimate(
    frame: pd.DataFrame, spec: dict[str, Any], edge_name: str, coordinate: str
) -> dict[str, Any]:
    predictor, response, controls = _edge_fields(spec, edge_name, coordinate)
    required = [predictor, response, *controls]
    primary: dict[str, float] = {}
    support: dict[str, int] = {}
    phase: dict[str, float] = {}
    phase_support: dict[str, int] = {}
    for group_name, group in _analysis_groups(frame, coordinate):
        rho, n = partial_rank_correlation(group, predictor, response, controls)
        if n < _minimum_support(spec, coordinate) or not np.isfinite(rho):
            raise IndustryDynamicsError(
                f"support/estimate failed: {edge_name}:{coordinate}:{group_name}:{n}"
            )
        primary[group_name] = rho
        support[group_name] = n
        phase_group = _phase_zero(group, required)
        phase_rho, phase_n = partial_rank_correlation(phase_group, predictor, response, controls)
        if phase_n <= len(controls) + 3 or not np.isfinite(phase_rho):
            raise IndustryDynamicsError(
                f"phase-zero estimate failed: {edge_name}:{coordinate}:{group_name}:{phase_n}"
            )
        phase[group_name] = phase_rho
        phase_support[group_name] = phase_n
    values = np.asarray(list(primary.values()), dtype=float)
    phase_values = np.asarray(list(phase.values()), dtype=float)
    median = float(np.median(values))
    median_sign = int(np.sign(median))
    return {
        "by_group": primary,
        "support_by_group": support,
        "median_partial_rho": median,
        "median_absolute_partial_rho": float(np.median(np.abs(values))),
        "median_sign": median_sign,
        "group_sign_support": int(np.sum(np.sign(values) == median_sign)),
        "phase_zero_by_group": phase,
        "phase_zero_support_by_group": phase_support,
        "phase_zero_median_partial_rho": float(np.median(phase_values)),
        "phase_zero_median_absolute_partial_rho": float(np.median(np.abs(phase_values))),
        "phase_zero_group_sign_support": int(np.sum(np.sign(phase_values) == median_sign)),
    }


def _edge_gate(spec: dict[str, Any], blocks: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    discovery_raw = blocks["discovery"]["raw"]
    confirmation_raw = blocks["confirmation_untouched_before_specification"]["raw"]
    raw_sign = discovery_raw["median_sign"]
    checks: dict[str, bool] = {
        "raw_discovery_effect": discovery_raw["median_absolute_partial_rho"]
        >= gates["raw_median_absolute_partial_rho_minimum"],
        "raw_confirmation_effect": confirmation_raw["median_absolute_partial_rho"]
        >= gates["raw_median_absolute_partial_rho_minimum"],
        "raw_block_sign_replication": raw_sign != 0 and confirmation_raw["median_sign"] == raw_sign,
        "raw_confirmation_magnitude": confirmation_raw["median_absolute_partial_rho"]
        >= gates["confirmation_to_discovery_absolute_magnitude_ratio_minimum"]
        * discovery_raw["median_absolute_partial_rho"],
    }
    for block_name in BLOCK_NAMES:
        raw = blocks[block_name]["raw"]
        pit = blocks[block_name]["pit"]
        checks[f"{block_name}:raw_sign_support"] = (
            raw["group_sign_support"] >= gates["raw_group_sign_support_minimum_of_8"]
        )
        checks[f"{block_name}:phase_zero_effect"] = (
            raw["phase_zero_median_absolute_partial_rho"]
            >= gates["phase_zero_raw_median_absolute_partial_rho_minimum"]
        )
        checks[f"{block_name}:phase_zero_sign"] = (
            int(np.sign(raw["phase_zero_median_partial_rho"])) == raw_sign
        )
        checks[f"{block_name}:pit_effect"] = (
            pit["median_absolute_partial_rho"] >= gates["pit_median_absolute_partial_rho_minimum"]
        )
        checks[f"{block_name}:pit_sign"] = pit["median_sign"] == raw_sign
        checks[f"{block_name}:pit_sign_support"] = (
            pit["group_sign_support"] >= gates["pit_group_sign_support_minimum_of_8"]
        )
        for coordinate in ("relative_to_all", "relative_rank"):
            relative = blocks[block_name][coordinate]
            checks[f"{block_name}:{coordinate}_effect"] = (
                relative["median_absolute_partial_rho"]
                >= gates["relative_median_absolute_partial_rho_minimum"]
            )
            checks[f"{block_name}:{coordinate}_sign"] = relative["median_sign"] == raw_sign
            checks[f"{block_name}:{coordinate}_sign_support"] = (
                relative["group_sign_support"]
                >= gates["relative_group_sign_support_minimum_of_2"]
            )
    return {"checks": checks, "edge_gate_pass": bool(all(checks.values()))}


def analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for edge_name in spec["edges"]:
        blocks: dict[str, Any] = {}
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, block_name)
            blocks[block_name] = {
                coordinate: _coordinate_block_estimate(frame, spec, edge_name, coordinate)
                for coordinate in COORDINATES
            }
        output[edge_name] = {"blocks": blocks, **_edge_gate(spec, blocks)}
    return output


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-INDRS-DYN-001 industry leadership dynamics",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        "- Future market state read: next-block rank rotation and five-session winner-diffusion change only.",
        "- Market/stock returns, selection outcomes, strategy fields, failed roles, failed MA fields, and CY-011 read: **none**.",
        "- Any passing edge is a state dynamic, not return prediction, timing, habitat, causality, or a rule.",
        "",
        "## Temporal edges",
        "",
        "| Edge | Raw discovery rho | Raw confirmation rho | PIT discovery rho | PIT confirmation rho | Phase-zero discovery rho | Phase-zero confirmation rho | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for edge_name in spec["edges"]:
        edge = result["edge_diagnostics"][edge_name]
        discovery = edge["blocks"]["discovery"]
        confirmation = edge["blocks"]["confirmation_untouched_before_specification"]
        lines.append(
            f"| `{edge_name}` | {discovery['raw']['median_partial_rho']:.3f} | "
            f"{confirmation['raw']['median_partial_rho']:.3f} | "
            f"{discovery['pit']['median_partial_rho']:.3f} | "
            f"{confirmation['pit']['median_partial_rho']:.3f} | "
            f"{discovery['raw']['phase_zero_median_partial_rho']:.3f} | "
            f"{confirmation['raw']['phase_zero_median_partial_rho']:.3f} | "
            f"{'PASS' if edge['edge_gate_pass'] else 'FAIL'} |"
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
    source = load_bound_input(spec)
    panel = construct_future_states(source, spec)
    diagnostics = analyze(panel, spec)
    accepted = [edge for edge in spec["edges"] if diagnostics[edge]["edge_gate_pass"]]
    rejected = [edge for edge in spec["edges"] if not diagnostics[edge]["edge_gate_pass"]]

    response_columns = [
        _response_name(response, coordinate)
        for response in spec["responses"]
        for coordinate in COORDINATES
    ]
    source_fields = _allowed_source_fields(spec)
    output = panel[[
        *KEYS, "geometry_decision_at", "future_trade_date", "response_available_at",
        *source_fields, *response_columns,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output["future_trade_date"] = output["future_trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(accepted)}_OF_{len(spec['edges'])}_TEMPORAL_EDGES_PASS",
        "usefulness_claim": "NONE",
        "future_market_state_fields_read": list(spec["responses"]),
        "market_return_fields_read": [],
        "stock_selection_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_industry_roles_read": [],
        "failed_ma_industry_fields_read": [],
        "cy011_read": False,
        "population": {
            "source_rows": int(len(source)),
            "response_rows": int(panel["future_trade_date"].notna().sum()),
            "groups": int(panel.groupby(["market_view", "denominator"]).ngroups),
            "first_predictor_date": str(panel["trade_date"].min().date()),
            "last_predictor_with_response": str(panel.loc[panel["future_trade_date"].notna(), "trade_date"].max().date()),
            "last_response_date": str(panel["future_trade_date"].max().date()),
        },
        "edge_diagnostics": diagnostics,
        "temporal_decision": {"accepted_edges": accepted, "rejected_edges": rejected},
        "confirmation_status": "UNTOUCHED_BEFORE_SPECIFICATION_THEN_CONSUMED_BY_THIS_EXPERIMENT",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "geometry_panel_sha256": spec["inputs"]["geometry_panel"]["sha256"],
            "geometry_result_sha256": spec["inputs"]["geometry_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
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
        "temporal_decision": completed["temporal_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
