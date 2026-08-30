#!/usr/bin/env python3
"""Run frozen size-participation precursor dynamics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
BASE_SCRIPT = PROGRAM / "scripts/run_mkt_style_dyn_001.py"
SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-PART-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-STYLE-PART-DYN-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-PART-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-PART-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "5cffae1f3e2a74ae3eb1db53041a4bf93f0ea79ef17ec52c31f5984c95d9fc42"
KEYS = ["trade_date", "market_view", "denominator"]
GROUP_KEYS = ["market_view", "denominator"]
BLOCK_NAMES = ("block_a_reused", "block_b_reused")
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")

MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_dyn_001", BASE_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-STYLE-DYN-001 estimator helpers")
base = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(base)


class StyleParticipationDynamicsError(RuntimeError):
    """Fail-closed MKT-STYLE-PART-DYN-001 error."""


sha256_file = base.sha256_file
_clean = base._clean
partial_rank_correlation = base.partial_rank_correlation
partial_within_date_correlation = base.partial_within_date_correlation
_future_date_name = base._future_date_name
_response_available_name = base._response_available_name
_response_name = base._response_name
_block_frame = base._block_frame
_analysis_groups = base._analysis_groups
_phase_zero = base._phase_zero


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StyleParticipationDynamicsError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_STATE_CONSTRUCTION":
        raise StyleParticipationDynamicsError(
            "spec is not frozen before future-state construction"
        )
    if spec["fields"]["primary_predictor"] != (
        "size_positive_participation_small30_large30"
    ):
        raise StyleParticipationDynamicsError("primary predictor changed")
    if spec["fields"]["predictor_neighbors"] != [
        "size_positive_participation_small20_large20",
        "size_positive_participation_small40_large40",
    ]:
        raise StyleParticipationDynamicsError("predictor neighbors changed")
    if spec["fields"]["response"] != "size_leadership_transition5":
        raise StyleParticipationDynamicsError("response identity changed")
    if len(spec["fields"]["controls"]) != 3:
        raise StyleParticipationDynamicsError("exactly three controls required")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise StyleParticipationDynamicsError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_results(paths: dict[str, Path]) -> None:
    style = json.loads(paths["style_result"].read_text(encoding="utf-8"))
    geometry = json.loads(paths["style_geometry_result"].read_text(encoding="utf-8"))
    risk = json.loads(paths["risk_result"].read_text(encoding="utf-8"))
    failed_self = json.loads(
        paths["failed_self_process_result"].read_text(encoding="utf-8")
    )
    expected_style = [
        "size_structure",
        "positive_participation_balance",
        "winner_diffusion",
        "positive_mass_concentration",
        "size_curve_divergence",
        "leadership_transition",
    ]
    if style["compression"]["accepted_roles"] != expected_style:
        raise StyleParticipationDynamicsError("style accepted-role identity mismatch")
    expected_geometry = [
        "positive_participation_balance",
        "winner_diffusion",
        "positive_mass_concentration",
        "size_curve_divergence",
        "leadership_transition",
    ]
    if geometry["compression"]["distinct_engine_coordinates"] != expected_geometry:
        raise StyleParticipationDynamicsError("direct-coordinate identity mismatch")
    if risk["minimal_panel"]["accepted_roles"] != [
        "central_direction",
        "upside_extreme_participation",
        "downside_extreme_participation",
    ]:
        raise StyleParticipationDynamicsError("risk accepted-role identity mismatch")
    if failed_self["status"] != "COMPLETE_STATE_DYNAMIC_FAIL":
        raise StyleParticipationDynamicsError("bounded precursor prerequisite changed")
    if failed_self["decision"]["state_dynamic_gate_pass"] is not False:
        raise StyleParticipationDynamicsError("self-process failure boundary changed")
    for name, result in (
        ("style", style),
        ("geometry", geometry),
        ("risk", risk),
        ("failed_self", failed_self),
    ):
        if result.get("usefulness_claim") != "NONE":
            raise StyleParticipationDynamicsError(f"{name} usefulness boundary changed")


def _style_field(field: str, coordinate: str) -> str:
    return field + {
        "raw": "",
        "pit": "__pit_3y_pct",
        "relative_to_all": "__relative_to_all",
        "relative_rank": "__relative_view_rank_pct",
    }[coordinate]


def _risk_field(field: str, coordinate: str) -> str:
    return field + {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]


def _predictor_fields(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec["fields"]["primary_predictor"]
    return {coordinate: _style_field(raw, coordinate) for coordinate in COORDINATES}


def _response_fields(spec: dict[str, Any]) -> dict[str, str]:
    raw = spec["fields"]["response"]
    return {coordinate: _style_field(raw, coordinate) for coordinate in COORDINATES}


def _control_fields(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for name, item in spec["fields"]["controls"].items():
        builder = _style_field if item["source"] == "style" else _risk_field
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
    try:
        return base._audit_source(
            source, frame, expected_rows, expected_first, expected_last
        )
    except base.StyleDynamicsError as exc:
        raise StyleParticipationDynamicsError(str(exc)) from exc


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths = _input_paths(spec)
    _validate_results(paths)
    predictors = _predictor_fields(spec)
    responses = _response_fields(spec)
    controls = _control_fields(spec)
    style_controls = [
        field
        for name, mapping in controls.items()
        if spec["fields"]["controls"][name]["source"] == "style"
        for field in mapping.values()
    ]
    risk_controls = [
        field
        for name, mapping in controls.items()
        if spec["fields"]["controls"][name]["source"] == "risk"
        for field in mapping.values()
    ]
    neighbors = spec["fields"]["predictor_neighbors"]
    style_fields = list(
        dict.fromkeys(
            [*predictors.values(), *responses.values(), *neighbors, *style_controls]
        )
    )
    style = pd.read_csv(
        paths["style_panel"],
        usecols=[*KEYS, "decision_at", "available_at", *style_fields],
    )
    risk = pd.read_csv(
        paths["risk_panel"],
        usecols=[*KEYS, "decision_at", "available_at", *risk_controls],
    )
    style_audit = _audit_source(
        "style", style, 11656, "2018-01-02", spec["population"]["date_end"]
    )
    risk_audit = _audit_source(
        "risk",
        risk,
        spec["population"]["expected_rows"],
        spec["population"]["date_start"],
        spec["population"]["date_end"],
    )
    style_values = style[[*KEYS, "decision_at", "available_at", *style_fields]]
    risk_values = risk[[*KEYS, *risk_controls]]
    merged = risk[KEYS].merge(
        style_values, on=KEYS, how="left", validate="one_to_one"
    ).merge(risk_values, on=KEYS, how="left", validate="one_to_one")
    if len(merged) != spec["population"]["expected_rows"]:
        raise StyleParticipationDynamicsError("common population mismatch")
    if merged.duplicated(KEYS).any():
        raise StyleParticipationDynamicsError("common key duplication")
    return (
        merged.sort_values(GROUP_KEYS + ["trade_date"]).reset_index(drop=True),
        {"style": style_audit, "risk": risk_audit},
    )


def construct_future_state(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.copy().sort_values(GROUP_KEYS + ["trade_date"]).reset_index(drop=True)
    grouped = out.groupby(GROUP_KEYS, sort=False)
    horizon = 5
    future_date = _future_date_name(horizon)
    response_time = _response_available_name(horizon)
    out[future_date] = grouped["trade_date"].shift(-horizon)
    out[response_time] = out[future_date].dt.strftime("%Y-%m-%dT15:00:00+08:00")
    for field in _response_fields(spec).values():
        out[_response_name(field, horizon)] = grouped[field].shift(-horizon)
    if int(out[future_date].isna().sum()) != horizon * 8:
        raise StyleParticipationDynamicsError("future tail count mismatch")
    predictor_time = pd.to_datetime(out["available_at"], errors="raise", utc=True)
    response_timestamp = pd.to_datetime(out[response_time], errors="coerce", utc=True)
    observed = response_timestamp.notna()
    if not (response_timestamp.loc[observed] > predictor_time.loc[observed]).all():
        raise StyleParticipationDynamicsError("response timestamp is not later")
    for _, group in out.groupby(GROUP_KEYS, sort=True):
        if not group[future_date].equals(group["trade_date"].shift(-horizon)):
            raise StyleParticipationDynamicsError("future date shift mismatch")
        for field in _response_fields(spec).values():
            if not group[_response_name(field, horizon)].equals(
                group[field].shift(-horizon)
            ):
                raise StyleParticipationDynamicsError(
                    f"future response shift mismatch: {field}"
                )
    return out.sort_values(KEYS).reset_index(drop=True)


def _tasks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    predictors = _predictor_fields(spec)
    responses = _response_fields(spec)
    tasks = [
        {
            "name": f"primary_{coordinate}",
            "predictor": predictors[coordinate],
            "response": responses[coordinate],
            "coordinate": coordinate,
            "phase_zero": False,
        }
        for coordinate in COORDINATES
    ]
    for neighbor in spec["fields"]["predictor_neighbors"]:
        tasks.append(
            {
                "name": f"neighbor_raw__{neighbor}",
                "predictor": neighbor,
                "response": responses["raw"],
                "coordinate": "raw",
                "phase_zero": False,
            }
        )
    tasks.append(
        {
            "name": "phase_zero_primary_raw",
            "predictor": predictors["raw"],
            "response": responses["raw"],
            "coordinate": "raw",
            "phase_zero": True,
        }
    )
    return tasks


def _controls(spec: dict[str, Any], coordinate: str) -> list[str]:
    fields = _control_fields(spec)
    return [fields[name][coordinate] for name in spec["fields"]["controls"]]


def complete_support_audit(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    expected_views = set(spec["population"]["views"])
    audit: dict[str, Any] = {}
    for task in _tasks(spec):
        predictor = task["predictor"]
        response = _response_name(task["response"], 5)
        controls = _controls(spec, task["coordinate"])
        required = [predictor, response, *controls]
        task_audit: dict[str, Any] = {}
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, block_name, 5)
            cells: dict[str, Any] = {}
            for group_name, group in _analysis_groups(frame, task["coordinate"]):
                if task["coordinate"] == "relative_rank":
                    _, partial, observations, dates = partial_within_date_correlation(
                        group, predictor, response, controls, expected_views
                    )
                    if observations < gates["relative_rank_denominator_block_minimum_observations"]:
                        raise StyleParticipationDynamicsError(
                            f"relative-rank support failed: {task['name']}:{block_name}:{group_name}:{observations}"
                        )
                    if not np.isfinite(partial):
                        raise StyleParticipationDynamicsError(
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
                    raise StyleParticipationDynamicsError(
                        f"support failed: {task['name']}:{block_name}:{group_name}:{len(clean)}"
                    )
                if not all(nondegenerate.values()):
                    raise StyleParticipationDynamicsError(
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
    predictor = task["predictor"]
    response = _response_name(task["response"], 5)
    controls = _controls(spec, task["coordinate"])
    expected_views = set(spec["population"]["views"])
    blocks: dict[str, Any] = {}
    for block_name in BLOCK_NAMES:
        frame = _block_frame(panel, spec, block_name, 5)
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
                raise StyleParticipationDynamicsError(
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
    return {**task, "response_field": response, "controls": controls, "blocks": blocks}


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
    primary = diagnostics["primary_raw"]
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
        "phase_zero_primary_raw": (
            "phase_zero_raw_median_absolute_partial_rho_minimum",
            "phase_zero_raw_group_sign_support_minimum_of_8",
        ),
        "primary_pit": (
            "primary_pit_median_absolute_partial_rho_minimum",
            "primary_pit_group_sign_support_minimum_of_8",
        ),
        "primary_relative_to_all": (
            "primary_relative_to_all_median_absolute_partial_rho_minimum",
            "primary_relative_to_all_group_sign_support_minimum_of_6",
        ),
        "primary_relative_rank": (
            "primary_relative_rank_absolute_partial_rho_minimum",
            "primary_relative_rank_sign_support_minimum_of_2",
        ),
    }
    for name in diagnostics:
        if name.startswith("neighbor_raw__"):
            task_gates[name] = (
                "neighbor_raw_median_absolute_partial_rho_minimum",
                "neighbor_raw_group_sign_support_minimum_of_8",
            )
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
    return {
        "learned_block_a_sign": learned_sign,
        "precursor_direction_if_passed": (
            "POSITIVE" if passed and learned_sign > 0 else "NEGATIVE" if passed else "NONE"
        ),
        "checks": checks,
        "precursor_gate_pass": passed,
    }


def analyze(
    panel: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    support = complete_support_audit(panel, spec)
    diagnostics = {
        task["name"]: _estimate_task(panel, spec, task) for task in _tasks(spec)
    }
    return support, diagnostics, _evaluate(spec, diagnostics)


def _render_report(result: dict[str, Any]) -> str:
    decision = result["decision"]
    lines = [
        "# MKT-STYLE-PART-DYN-001 size-participation precursor",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Precursor gate pass: `{decision['precursor_gate_pass']}`",
        f"- Passing direction label: `{decision['precursor_direction_if_passed']}`",
        "- Both temporal blocks reuse pre-2024 data; neither is fresh confirmation.",
        "- Future payoff, stock selection, strategy outcomes, additional edges, post-2023 data, and CY-011 read: **none**.",
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
    panel = construct_future_state(source, spec)
    support, diagnostics, decision = analyze(panel, spec)
    output = panel.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output[_future_date_name(5)] = output[_future_date_name(5)].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": (
            "COMPLETE_PRECURSOR_PASS"
            if decision["precursor_gate_pass"]
            else "COMPLETE_PRECURSOR_FAIL"
        ),
        "usefulness_claim": "NONE",
        "size_premium_claim": "NONE",
        "strategy_or_habitat_claim": "NONE",
        "future_size_state_fields_constructed": [
            "size_leadership_transition5@t+5"
        ],
        "future_market_payoff_fields_read": [],
        "future_stock_selection_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "additional_temporal_edges_read": [],
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
