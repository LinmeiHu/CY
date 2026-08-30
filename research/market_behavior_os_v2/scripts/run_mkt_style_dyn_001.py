#!/usr/bin/env python3
"""Run frozen nonoverlapping circulating-size transition dynamics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-STYLE-DYN-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "150de73b4a6c3c56027d61e63791636ede2c75e9e57785f7981263290a53a3e7"
KEYS = ["trade_date", "market_view", "denominator"]
GROUP_KEYS = ["market_view", "denominator"]
BLOCK_NAMES = ("block_a_reused", "block_b_reused")
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")


class StyleDynamicsError(RuntimeError):
    """Fail-closed MKT-STYLE-DYN-001 error."""


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
        raise StyleDynamicsError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_STATE_CONSTRUCTION":
        raise StyleDynamicsError("spec is not frozen before future-state construction")
    if spec["required_direct_engine_coordinate"] != "leadership_transition":
        raise StyleDynamicsError("direct-coordinate identity mismatch")
    if spec["fields"]["primary_transition"] != "size_leadership_transition5":
        raise StyleDynamicsError("primary transition changed")
    if spec["fields"]["neighbor_transitions"] != {
        "3": "size_leadership_transition3",
        "10": "size_leadership_transition10",
    }:
        raise StyleDynamicsError("neighbor transition identity mismatch")
    if len(spec["fields"]["controls"]) != 3:
        raise StyleDynamicsError("exactly three controls required")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise StyleDynamicsError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_results(paths: dict[str, Path]) -> None:
    style = json.loads(paths["style_result"].read_text(encoding="utf-8"))
    geometry = json.loads(paths["style_geometry_result"].read_text(encoding="utf-8"))
    volatility = json.loads(paths["volatility_result"].read_text(encoding="utf-8"))
    expected_style = [
        "size_structure",
        "positive_participation_balance",
        "winner_diffusion",
        "positive_mass_concentration",
        "size_curve_divergence",
        "leadership_transition",
    ]
    if style["compression"]["accepted_roles"] != expected_style:
        raise StyleDynamicsError("style accepted-role identity mismatch")
    expected_geometry = [
        "positive_participation_balance",
        "winner_diffusion",
        "positive_mass_concentration",
        "size_curve_divergence",
        "leadership_transition",
    ]
    if geometry["compression"]["distinct_engine_coordinates"] != expected_geometry:
        raise StyleDynamicsError("style direct-coordinate identity mismatch")
    expected_volatility = [
        "realized_volatility",
        "intraday_range",
        "volatility_concentration",
        "volatility_change",
    ]
    if volatility["minimal_panel"]["accepted_roles"] != expected_volatility:
        raise StyleDynamicsError("volatility accepted-role identity mismatch")
    for name, result in (
        ("style", style),
        ("geometry", geometry),
        ("volatility", volatility),
    ):
        if result.get("usefulness_claim") != "NONE":
            raise StyleDynamicsError(f"{name} usefulness boundary changed")


def _style_field(field: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "__pit_3y_pct",
        "relative_to_all": "__relative_to_all",
        "relative_rank": "__relative_view_rank_pct",
    }[coordinate]
    return field + suffix


def _volatility_field(field: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return field + suffix


def _primary_fields(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec["fields"]["primary_transition"]
    return {coordinate: _style_field(raw, coordinate) for coordinate in COORDINATES}


def _control_fields(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for name, item in spec["fields"]["controls"].items():
        builder = _style_field if item["source"] == "style" else _volatility_field
        output[name] = {
            coordinate: builder(item["field"], coordinate)
            for coordinate in COORDINATES
        }
    return output


def _audit_source(
    source: str,
    frame: pd.DataFrame,
    expected_rows: int,
    expected_first: str,
    expected_last: str,
) -> dict[str, Any]:
    if len(frame) != expected_rows or frame.duplicated(KEYS).any():
        raise StyleDynamicsError(f"{source} row/key audit failed")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if str(frame["trade_date"].min().date()) != expected_first:
        raise StyleDynamicsError(f"{source} first date mismatch")
    if str(frame["trade_date"].max().date()) != expected_last:
        raise StyleDynamicsError(f"{source} last date mismatch")
    decision = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
    available = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    if (available > decision).any():
        raise StyleDynamicsError(f"{source} time travel")
    local = available.dt.tz_convert("Asia/Shanghai")
    if not (local.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise StyleDynamicsError(f"{source} availability is not exact 15:00")
    if not (local.dt.date == frame["trade_date"].dt.date).all():
        raise StyleDynamicsError(f"{source} availability date mismatch")
    counts = frame.groupby(GROUP_KEYS, sort=True).size()
    if len(counts) != 8 or not (counts == expected_rows // 8).all():
        raise StyleDynamicsError(f"{source} group population mismatch")
    return {
        "rows": int(len(frame)),
        "groups": int(len(counts)),
        "first_date": expected_first,
        "last_date": expected_last,
    }


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = _input_paths(spec)
    _validate_results(paths)
    primary = _primary_fields(spec)
    controls = _control_fields(spec)
    style_controls = [
        field
        for name, mapping in controls.items()
        if spec["fields"]["controls"][name]["source"] == "style"
        for field in mapping.values()
    ]
    volatility_controls = [
        field
        for name, mapping in controls.items()
        if spec["fields"]["controls"][name]["source"] == "volatility"
        for field in mapping.values()
    ]
    neighbor_fields = list(spec["fields"]["neighbor_transitions"].values())
    style = pd.read_csv(
        paths["style_panel"],
        usecols=list(
            dict.fromkeys(
                [
                    *KEYS,
                    "decision_at",
                    "available_at",
                    *primary.values(),
                    *neighbor_fields,
                    *style_controls,
                ]
            )
        ),
    )
    volatility = pd.read_csv(
        paths["volatility_panel"],
        usecols=[
            *KEYS,
            "decision_at",
            "available_at",
            *volatility_controls,
        ],
    )
    style_audit = _audit_source(
        "style", style, 11656, "2018-01-02", spec["population"]["date_end"]
    )
    volatility_audit = _audit_source(
        "volatility",
        volatility,
        spec["population"]["expected_rows"],
        spec["population"]["date_start"],
        spec["population"]["date_end"],
    )
    style_values = style[[*KEYS, "decision_at", "available_at", *primary.values(), *neighbor_fields, *style_controls]]
    volatility_values = volatility[[*KEYS, *volatility_controls]]
    merged = volatility[KEYS].merge(
        style_values, on=KEYS, how="left", validate="one_to_one"
    ).merge(
        volatility_values, on=KEYS, how="left", validate="one_to_one"
    )
    if len(merged) != spec["population"]["expected_rows"]:
        raise StyleDynamicsError("common population mismatch")
    if merged.duplicated(KEYS).any():
        raise StyleDynamicsError("common key duplication")
    if set(merged["market_view"]) != set(spec["population"]["views"]):
        raise StyleDynamicsError("common view identity mismatch")
    if set(merged["denominator"]) != set(spec["population"]["denominators"]):
        raise StyleDynamicsError("common denominator identity mismatch")
    return (
        merged.sort_values(GROUP_KEYS + ["trade_date"]).reset_index(drop=True),
        {"style": style_audit, "volatility": volatility_audit},
    )


def _future_date_name(horizon: int) -> str:
    return f"future_trade_date_h{horizon}"


def _response_available_name(horizon: int) -> str:
    return f"response_available_at_h{horizon}"


def _response_name(field: str, horizon: int) -> str:
    return f"future_h{horizon}__{field}"


def construct_future_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.copy().sort_values(GROUP_KEYS + ["trade_date"]).reset_index(drop=True)
    grouped = out.groupby(GROUP_KEYS, sort=False)
    fields_by_horizon = {
        3: [spec["fields"]["neighbor_transitions"]["3"]],
        5: list(_primary_fields(spec).values()),
        10: [spec["fields"]["neighbor_transitions"]["10"]],
    }
    predictor_timestamp = pd.to_datetime(out["available_at"], errors="raise", utc=True)
    for horizon, fields in fields_by_horizon.items():
        future_date = _future_date_name(horizon)
        response_time = _response_available_name(horizon)
        out[future_date] = grouped["trade_date"].shift(-horizon)
        out[response_time] = out[future_date].dt.strftime("%Y-%m-%dT15:00:00+08:00")
        for field in fields:
            out[_response_name(field, horizon)] = grouped[field].shift(-horizon)
        if int(out[future_date].isna().sum()) != horizon * 8:
            raise StyleDynamicsError(f"future tail count mismatch at h={horizon}")
        response_timestamp = pd.to_datetime(out[response_time], errors="coerce", utc=True)
        observed = response_timestamp.notna()
        if not (
            response_timestamp.loc[observed] > predictor_timestamp.loc[observed]
        ).all():
            raise StyleDynamicsError(f"response timestamp is not later at h={horizon}")
        for _, group in out.groupby(GROUP_KEYS, sort=True):
            if not group[future_date].equals(group["trade_date"].shift(-horizon)):
                raise StyleDynamicsError(f"future date shift mismatch at h={horizon}")
            for field in fields:
                if not group[_response_name(field, horizon)].equals(
                    group[field].shift(-horizon)
                ):
                    raise StyleDynamicsError(f"future state shift mismatch: {field}:h{horizon}")
    return out.sort_values(KEYS).reset_index(drop=True)


def partial_rank_correlation(
    frame: pd.DataFrame,
    predictor: str,
    response: str,
    controls: list[str],
) -> tuple[float, float, int]:
    clean = frame[[predictor, response, *controls]].replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(clean) <= len(controls) + 3:
        return float("nan"), float("nan"), int(len(clean))
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    unadjusted = float(np.corrcoef(ranked[:, 0], ranked[:, 1])[0, 1])
    design = np.column_stack([np.ones(len(ranked), dtype=float), ranked[:, 2:]])
    predictor_residual = ranked[:, 0] - design @ np.linalg.lstsq(
        design, ranked[:, 0], rcond=None
    )[0]
    response_residual = ranked[:, 1] - design @ np.linalg.lstsq(
        design, ranked[:, 1], rcond=None
    )[0]
    if np.std(predictor_residual) == 0.0 or np.std(response_residual) == 0.0:
        return unadjusted, float("nan"), int(len(clean))
    partial = float(np.corrcoef(predictor_residual, response_residual)[0, 1])
    return unadjusted, partial, int(len(clean))


def partial_within_date_correlation(
    frame: pd.DataFrame,
    predictor: str,
    response: str,
    controls: list[str],
    expected_views: set[str],
) -> tuple[float, float, int, int]:
    required = [predictor, response, *controls]
    pieces: list[pd.DataFrame] = []
    for _, date_frame in frame.groupby("trade_date", sort=True):
        if len(date_frame) != len(expected_views):
            continue
        if set(date_frame["market_view"]) != expected_views:
            continue
        values = date_frame[required].replace([np.inf, -np.inf], np.nan)
        if values.isna().any().any():
            continue
        if not all(values[field].nunique() > 1 for field in required):
            continue
        pieces.append(date_frame[["trade_date", *required]])
    if not pieces:
        return float("nan"), float("nan"), 0, 0
    clean = pd.concat(pieces, ignore_index=True)
    values = clean[required].astype(float)
    demeaned = values - values.groupby(clean["trade_date"]).transform("mean")
    predictor_values = demeaned[predictor].to_numpy(dtype=float)
    response_values = demeaned[response].to_numpy(dtype=float)
    control_values = demeaned[controls].to_numpy(dtype=float)
    unadjusted = float(np.corrcoef(predictor_values, response_values)[0, 1])
    predictor_residual = predictor_values - control_values @ np.linalg.lstsq(
        control_values, predictor_values, rcond=None
    )[0]
    response_residual = response_values - control_values @ np.linalg.lstsq(
        control_values, response_values, rcond=None
    )[0]
    if np.std(predictor_residual) == 0.0 or np.std(response_residual) == 0.0:
        return unadjusted, float("nan"), int(len(clean)), int(len(pieces))
    partial = float(np.corrcoef(predictor_residual, response_residual)[0, 1])
    return unadjusted, partial, int(len(clean)), int(len(pieces))


def _block_frame(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    block_name: str,
    horizon: int,
) -> pd.DataFrame:
    block = spec["temporal_blocks"][block_name]
    start = pd.Timestamp(block["start"])
    end = pd.Timestamp(block["end"])
    return panel.loc[
        panel["trade_date"].between(start, end)
        & panel[_future_date_name(horizon)].between(start, end)
    ].copy()


def _tasks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    primary = _primary_fields(spec)
    tasks = [
        {
            "name": f"primary_{coordinate}_h5",
            "field": field,
            "coordinate": coordinate,
            "horizon": 5,
            "phase_zero": False,
        }
        for coordinate, field in primary.items()
    ]
    tasks.extend(
        [
            {
                "name": "neighbor_raw_h3",
                "field": spec["fields"]["neighbor_transitions"]["3"],
                "coordinate": "raw",
                "horizon": 3,
                "phase_zero": False,
            },
            {
                "name": "neighbor_raw_h10",
                "field": spec["fields"]["neighbor_transitions"]["10"],
                "coordinate": "raw",
                "horizon": 10,
                "phase_zero": False,
            },
            {
                "name": "phase_zero_primary_raw_h5",
                "field": primary["raw"],
                "coordinate": "raw",
                "horizon": 5,
                "phase_zero": True,
            },
        ]
    )
    return tasks


def _controls(spec: dict[str, Any], coordinate: str) -> list[str]:
    controls = _control_fields(spec)
    return [controls[name][coordinate] for name in spec["fields"]["controls"]]


def _analysis_groups(
    frame: pd.DataFrame,
    coordinate: str,
) -> list[tuple[str, pd.DataFrame]]:
    if coordinate == "relative_to_all":
        work = frame.loc[frame["market_view"] != "ALL_A"]
        return [
            (f"{view}:{denominator}", group)
            for (view, denominator), group in work.groupby(GROUP_KEYS, sort=True)
        ]
    if coordinate == "relative_rank":
        return [
            (str(denominator), group)
            for denominator, group in frame.groupby("denominator", sort=True)
        ]
    return [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in frame.groupby(GROUP_KEYS, sort=True)
    ]


def _phase_zero(group: pd.DataFrame, required: list[str]) -> pd.DataFrame:
    clean = group.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    return clean.sort_values("trade_date").iloc[::5].copy()


def complete_support_audit(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    expected_views = set(spec["population"]["views"])
    audit: dict[str, Any] = {}
    for task in _tasks(spec):
        task_audit: dict[str, Any] = {}
        predictor = task["field"]
        response = _response_name(predictor, task["horizon"])
        controls = _controls(spec, task["coordinate"])
        required = [predictor, response, *controls]
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, block_name, task["horizon"])
            cells: dict[str, Any] = {}
            for group_name, group in _analysis_groups(frame, task["coordinate"]):
                if task["coordinate"] == "relative_rank":
                    _, partial, observations, dates = partial_within_date_correlation(
                        group, predictor, response, controls, expected_views
                    )
                    if observations < gates["relative_rank_denominator_block_minimum_observations"]:
                        raise StyleDynamicsError(
                            f"relative-rank support failed: {task['name']}:{block_name}:{group_name}:{observations}"
                        )
                    if not np.isfinite(partial):
                        raise StyleDynamicsError(
                            f"relative-rank nondegeneracy failed: {task['name']}:{block_name}:{group_name}"
                        )
                    cells[group_name] = {"observations": observations, "dates": dates}
                    continue
                selected = _phase_zero(group, required) if task["phase_zero"] else group
                clean = selected[required].replace([np.inf, -np.inf], np.nan).dropna()
                minimum = (
                    gates["phase_zero_group_block_minimum_observations"]
                    if task["phase_zero"]
                    else gates["ordinary_group_block_minimum_observations"]
                )
                nondegenerate = {
                    field: bool(clean[field].nunique() > 1) for field in required
                }
                if len(clean) < minimum:
                    raise StyleDynamicsError(
                        f"support failed: {task['name']}:{block_name}:{group_name}:{len(clean)}"
                    )
                if not all(nondegenerate.values()):
                    raise StyleDynamicsError(
                        f"nondegeneracy failed: {task['name']}:{block_name}:{group_name}"
                    )
                cells[group_name] = {
                    "observations": int(len(clean)),
                    "nondegenerate": nondegenerate,
                }
            task_audit[block_name] = cells
        audit[task["name"]] = task_audit
    return audit


def _estimate_task(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    task: dict[str, Any],
) -> dict[str, Any]:
    predictor = task["field"]
    response = _response_name(predictor, task["horizon"])
    controls = _controls(spec, task["coordinate"])
    expected_views = set(spec["population"]["views"])
    blocks: dict[str, Any] = {}
    for block_name in BLOCK_NAMES:
        frame = _block_frame(panel, spec, block_name, task["horizon"])
        by_group: dict[str, Any] = {}
        for group_name, group in _analysis_groups(frame, task["coordinate"]):
            if task["coordinate"] == "relative_rank":
                unadjusted, partial, observations, dates = partial_within_date_correlation(
                    group, predictor, response, controls, expected_views
                )
                extra = {"dates": dates}
            else:
                required = [predictor, response, *controls]
                selected = _phase_zero(group, required) if task["phase_zero"] else group
                unadjusted, partial, observations = partial_rank_correlation(
                    selected, predictor, response, controls
                )
                extra = {}
            if not np.isfinite(unadjusted) or not np.isfinite(partial):
                raise StyleDynamicsError(
                    f"estimate failed: {task['name']}:{block_name}:{group_name}"
                )
            by_group[group_name] = {
                "observations": observations,
                "unadjusted_spearman": unadjusted,
                "partial_spearman": partial,
                **extra,
            }
        partials = np.asarray(
            [item["partial_spearman"] for item in by_group.values()], dtype=float
        )
        unadjusted_values = np.asarray(
            [item["unadjusted_spearman"] for item in by_group.values()], dtype=float
        )
        blocks[block_name] = {
            "by_group": by_group,
            "median_unadjusted_spearman": float(np.median(unadjusted_values)),
            "median_partial_rho": float(np.median(partials)),
            "median_absolute_partial_rho": float(np.median(np.abs(partials))),
        }
    return {**task, "controls": controls, "blocks": blocks}


def _sign_support(task: dict[str, Any], block_name: str, sign: int) -> int:
    values = np.asarray(
        [
            item["partial_spearman"]
            for item in task["blocks"][block_name]["by_group"].values()
        ],
        dtype=float,
    )
    return int(np.sum(np.sign(values) == sign))


def _evaluate(spec: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    primary = diagnostics["primary_raw_h5"]
    block_a = primary["blocks"][BLOCK_NAMES[0]]
    block_b = primary["blocks"][BLOCK_NAMES[1]]
    learned_sign = int(np.sign(block_a["median_partial_rho"]))
    checks: dict[str, bool] = {
        "primary_nonzero_block_a_sign": learned_sign != 0,
        "primary_raw_block_a_effect": block_a["median_absolute_partial_rho"]
        >= gates["primary_raw_median_absolute_partial_rho_minimum"],
        "primary_raw_block_b_effect": block_b["median_absolute_partial_rho"]
        >= gates["primary_raw_median_absolute_partial_rho_minimum"],
        "primary_raw_block_b_sign": int(np.sign(block_b["median_partial_rho"]))
        == learned_sign,
        "primary_raw_block_a_sign_support": _sign_support(
            primary, BLOCK_NAMES[0], learned_sign
        )
        >= gates["primary_raw_group_sign_support_minimum_of_8"],
        "primary_raw_block_b_sign_support": _sign_support(
            primary, BLOCK_NAMES[1], learned_sign
        )
        >= gates["primary_raw_group_sign_support_minimum_of_8"],
        "primary_raw_block_b_magnitude": block_b["median_absolute_partial_rho"]
        >= gates["block_b_to_block_a_absolute_magnitude_ratio_minimum"]
        * block_a["median_absolute_partial_rho"],
    }
    task_gates = {
        "phase_zero_primary_raw_h5": (
            "phase_zero_raw_median_absolute_partial_rho_minimum",
            "phase_zero_raw_group_sign_support_minimum_of_8",
        ),
        "primary_pit_h5": (
            "primary_pit_median_absolute_partial_rho_minimum",
            "primary_pit_group_sign_support_minimum_of_8",
        ),
        "primary_relative_to_all_h5": (
            "primary_relative_to_all_median_absolute_partial_rho_minimum",
            "primary_relative_to_all_group_sign_support_minimum_of_6",
        ),
        "primary_relative_rank_h5": (
            "primary_relative_rank_absolute_partial_rho_minimum",
            "primary_relative_rank_sign_support_minimum_of_2",
        ),
        "neighbor_raw_h3": (
            "neighbor_raw_median_absolute_partial_rho_minimum",
            "neighbor_raw_group_sign_support_minimum_of_8",
        ),
        "neighbor_raw_h10": (
            "neighbor_raw_median_absolute_partial_rho_minimum",
            "neighbor_raw_group_sign_support_minimum_of_8",
        ),
    }
    for name, (effect_gate, support_gate) in task_gates.items():
        task = diagnostics[name]
        for block_name in BLOCK_NAMES:
            block = task["blocks"][block_name]
            checks[f"{name}:{block_name}:effect"] = (
                block["median_absolute_partial_rho"] >= gates[effect_gate]
            )
            checks[f"{name}:{block_name}:sign"] = (
                int(np.sign(block["median_partial_rho"])) == learned_sign
            )
            checks[f"{name}:{block_name}:sign_support"] = (
                _sign_support(task, block_name, learned_sign) >= gates[support_gate]
            )
    passed = bool(all(checks.values()))
    process = "NONE"
    if passed:
        process = "PERSISTENCE" if learned_sign > 0 else "REVERSAL"
    return {
        "learned_block_a_sign": learned_sign,
        "process_if_passed": process,
        "checks": checks,
        "state_dynamic_gate_pass": passed,
    }


def analyze(
    panel: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    support = complete_support_audit(panel, spec)
    diagnostics = {
        task["name"]: _estimate_task(panel, spec, task) for task in _tasks(spec)
    }
    decision = _evaluate(spec, diagnostics)
    return support, diagnostics, decision


def _render_report(result: dict[str, Any]) -> str:
    decision = result["decision"]
    lines = [
        "# MKT-STYLE-DYN-001 circulating-size transition dynamics",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- State dynamic gate pass: `{decision['state_dynamic_gate_pass']}`",
        f"- Passing process label: `{decision['process_if_passed']}`",
        "- Both temporal blocks reuse pre-2024 data; neither is fresh confirmation.",
        "- Future market payoff, stock selection, strategy outcomes, post-2023 data, and CY-011 read: **none**.",
        "",
        "## Primary and challenges",
        "",
        "| Task | Block A median partial rho | Block B median partial rho |",
        "|---|---:|---:|",
    ]
    for name, item in result["diagnostics"].items():
        a = item["blocks"][BLOCK_NAMES[0]]["median_partial_rho"]
        b = item["blocks"][BLOCK_NAMES[1]]["median_partial_rho"]
        lines.append(f"| `{name}` | {a:.3f} | {b:.3f} |")
    failed = [name for name, passed in decision["checks"].items() if not passed]
    lines.extend(
        [
            "",
            "## Gate summary",
            "",
            f"- Passed checks: {sum(decision['checks'].values())}/{len(decision['checks'])}.",
            f"- Failed checks: `{json.dumps(failed, sort_keys=True)}`",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    source, input_audit = load_bound_inputs(spec)
    panel = construct_future_states(source, spec)
    support, diagnostics, decision = analyze(panel, spec)
    output = panel.copy()
    for field in [
        "trade_date",
        _future_date_name(3),
        _future_date_name(5),
        _future_date_name(10),
    ]:
        output[field] = output[field].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": (
            "COMPLETE_STATE_DYNAMIC_PASS"
            if decision["state_dynamic_gate_pass"]
            else "COMPLETE_STATE_DYNAMIC_FAIL"
        ),
        "usefulness_claim": "NONE",
        "size_premium_claim": "NONE",
        "strategy_or_habitat_claim": "NONE",
        "future_size_state_fields_constructed": [
            "size_leadership_transition3@t+3",
            "size_leadership_transition5@t+5",
            "size_leadership_transition10@t+10",
        ],
        "future_market_payoff_fields_read": [],
        "future_stock_selection_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_or_redundant_size_predictors_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "input_audit": input_audit,
        "population": {
            "rows": int(len(output)),
            "groups": int(output.groupby(GROUP_KEYS).ngroups),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
        },
        "complete_support_audit": support,
        "diagnostics": diagnostics,
        "decision": decision,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "bound_inputs": {
                name: entry["sha256"] for name, entry in spec["inputs"].items()
            },
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "decision": completed["decision"],
                "panel_sha256": completed["hashes"]["panel_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
