#!/usr/bin/env python3
"""Run frozen outcome-blind VWAP defense/recovery state dynamics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-DEF-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-DEF-DYN-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-DEF-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-DEF-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "b53452c922eff99ac9d8a367dc905b00b08335beec337e8507144b686423ecee"
KEYS = ["trade_date", "market_view", "denominator"]
GROUP_KEYS = ["market_view", "denominator"]
BLOCK_NAMES = ("block_a_reused_exploration", "block_b_reused_validation")


class MinuteDefenseDynamicsError(RuntimeError):
    """Fail-closed MKT-MIN-DEF-DYN-001 error."""


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
        raise MinuteDefenseDynamicsError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_STATE_CONSTRUCTION":
        raise MinuteDefenseDynamicsError("spec is not frozen before future-state construction")
    if spec["required_accepted_coordinate"] != "vwap_defense_recovery":
        raise MinuteDefenseDynamicsError("accepted-coordinate identity mismatch")
    if spec["responses"]["primary_horizon_sessions"] != 1:
        raise MinuteDefenseDynamicsError("primary horizon changed")
    if spec["responses"]["neighbor_horizon_sessions"] != [3, 5]:
        raise MinuteDefenseDynamicsError("neighbor horizons changed")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise MinuteDefenseDynamicsError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_mechanism_result(path: Path) -> None:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result["compression"]["accepted_mechanisms"] != ["vwap_defense_recovery"]:
        raise MinuteDefenseDynamicsError("accepted mechanism set changed")
    if result["usefulness_claim"] != "NONE":
        raise MinuteDefenseDynamicsError("source usefulness boundary changed")
    if result["future_state_fields_read"] or result["strategy_or_outcome_fields_read"]:
        raise MinuteDefenseDynamicsError("source access boundary changed")
    if result["cross_day_support_claim"] != "NONE":
        raise MinuteDefenseDynamicsError("source cross-day support boundary changed")
    if result["participant_accumulation_claim"] != "NONE":
        raise MinuteDefenseDynamicsError("source participant boundary changed")


def _absolute_fields(spec: dict[str, Any]) -> list[str]:
    fields = spec["fields"]
    return [
        fields["primary"],
        *fields["aggregation_neighbors"],
        *fields["cross_section_neighbors"],
    ]


def _relative_control_name(field: str) -> str:
    return f"{field}__relative_to_all"


def _source_fields(spec: dict[str, Any]) -> list[str]:
    fields = spec["fields"]
    return list(dict.fromkeys([
        *_absolute_fields(spec),
        fields["relative_to_all"],
        fields["relative_rank"],
        *fields["controls_pit"],
        *fields["controls_relative_rank"],
    ]))


def load_bound_input(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_mechanism_result(paths["mechanism_result"])
    panel = pd.read_csv(
        paths["mechanism_panel"],
        usecols=[*KEYS, "available_at", "hard_valid", *_source_fields(spec)],
    )
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    panel["available_at"] = pd.to_datetime(panel["available_at"], errors="raise")
    if panel.duplicated(KEYS).any():
        raise MinuteDefenseDynamicsError("source key duplication")
    if not panel["hard_valid"].all():
        raise MinuteDefenseDynamicsError("source hard-valid boundary failed")
    if not (panel["available_at"].dt.strftime("%H:%M:%S") == "15:30:00").all():
        raise MinuteDefenseDynamicsError("predictor availability is not exact 15:30")
    if not (panel["available_at"].dt.date == panel["trade_date"].dt.date).all():
        raise MinuteDefenseDynamicsError("predictor date/availability mismatch")
    population = spec["population"]
    if set(panel["market_view"]) != set(population["views"]):
        raise MinuteDefenseDynamicsError("view identity mismatch")
    if set(panel["denominator"]) != set(population["denominators"]):
        raise MinuteDefenseDynamicsError("denominator identity mismatch")
    required = _source_fields(spec)
    complete = panel.loc[panel[spec["fields"]["primary"]].notna()].copy()
    if complete[required].isna().any().any():
        raise MinuteDefenseDynamicsError("required field incomplete after causal warm-up")
    if len(complete) != population["expected_complete_rows"]:
        raise MinuteDefenseDynamicsError("complete source population mismatch")
    if str(complete["trade_date"].min().date()) != population["date_start"]:
        raise MinuteDefenseDynamicsError("complete source start changed")
    if str(complete["trade_date"].max().date()) != population["date_end"]:
        raise MinuteDefenseDynamicsError("complete source end changed")
    counts = complete.groupby(GROUP_KEYS, sort=True).size()
    if len(counts) != 8 or not (counts == population["expected_complete_rows_per_group"]).all():
        raise MinuteDefenseDynamicsError("complete group population mismatch")
    return complete.sort_values(GROUP_KEYS + ["trade_date"]).reset_index(drop=True)


def _future_date_name(horizon: int) -> str:
    return f"future_trade_date_h{horizon}"


def _response_available_name(horizon: int) -> str:
    return f"response_available_at_h{horizon}"


def _response_name(field: str, horizon: int) -> str:
    return f"future_h{horizon}__{field}"


def construct_future_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.copy()
    all_mask = out["market_view"].eq("ALL_A")
    for control in spec["fields"]["controls_pit"]:
        all_value = out[control].where(all_mask).groupby(
            [out["trade_date"], out["denominator"]], sort=False
        ).transform("max")
        if all_value.isna().any():
            raise MinuteDefenseDynamicsError(f"ALL_A control baseline missing: {control}")
        out[_relative_control_name(control)] = out[control] - all_value

    state_fields = [
        *_absolute_fields(spec),
        spec["fields"]["relative_to_all"],
        spec["fields"]["relative_rank"],
    ]
    horizons = [
        spec["responses"]["primary_horizon_sessions"],
        *spec["responses"]["neighbor_horizon_sessions"],
    ]
    grouped = out.groupby(GROUP_KEYS, sort=False)
    for horizon in horizons:
        future_date = _future_date_name(horizon)
        response_time = _response_available_name(horizon)
        out[future_date] = grouped["trade_date"].shift(-horizon)
        out[response_time] = out[future_date].dt.strftime("%Y-%m-%dT15:30:00+08:00")
        for field in state_fields:
            out[_response_name(field, horizon)] = grouped[field].shift(-horizon)
        if int(out[future_date].isna().sum()) != horizon * 8:
            raise MinuteDefenseDynamicsError(f"future tail count mismatch at h={horizon}")
        response_timestamp = pd.to_datetime(out[response_time], errors="coerce", utc=True)
        predictor_timestamp = out["available_at"].dt.tz_localize("Asia/Shanghai").dt.tz_convert("UTC")
        observed = response_timestamp.notna()
        if not (response_timestamp.loc[observed] > predictor_timestamp.loc[observed]).all():
            raise MinuteDefenseDynamicsError(f"response is not later at h={horizon}")
        for _, group in out.groupby(GROUP_KEYS, sort=True):
            if not group[future_date].equals(group["trade_date"].shift(-horizon)):
                raise MinuteDefenseDynamicsError(f"future date is not exact shift at h={horizon}")
    return out.sort_values(KEYS).reset_index(drop=True)


def partial_rank_correlation(
    frame: pd.DataFrame, predictor: str, response: str, controls: list[str]
) -> tuple[float, float, int]:
    clean = frame[[predictor, response, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
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


def _block_frame(
    panel: pd.DataFrame, spec: dict[str, Any], block_name: str, horizon: int
) -> pd.DataFrame:
    block = spec["temporal_blocks"][block_name]
    start = pd.Timestamp(block["start"])
    end = pd.Timestamp(block["end"])
    return panel.loc[
        panel["trade_date"].between(start, end)
        & panel[_future_date_name(horizon)].between(start, end)
    ].copy()


def _analysis_groups(
    frame: pd.DataFrame, coordinate: str
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


def _controls(spec: dict[str, Any], coordinate: str) -> list[str]:
    if coordinate == "absolute":
        return list(spec["fields"]["controls_pit"])
    if coordinate == "relative_to_all":
        return [_relative_control_name(field) for field in spec["fields"]["controls_pit"]]
    return list(spec["fields"]["controls_relative_rank"])


def _tasks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    fields = spec["fields"]
    tasks = [
        {"name": f"absolute_primary_h{horizon}", "field": fields["primary"],
         "coordinate": "absolute", "horizon": horizon}
        for horizon in [1, 3, 5]
    ]
    tasks.extend(
        {"name": f"h1_shape__{field}", "field": field,
         "coordinate": "absolute", "horizon": 1}
        for field in [*fields["aggregation_neighbors"], *fields["cross_section_neighbors"]]
    )
    tasks.extend([
        {"name": "h1_relative_to_all", "field": fields["relative_to_all"],
         "coordinate": "relative_to_all", "horizon": 1},
        {"name": "h1_relative_rank", "field": fields["relative_rank"],
         "coordinate": "relative_rank", "horizon": 1},
    ])
    return tasks


def _minimum_support(spec: dict[str, Any], coordinate: str) -> int:
    gates = spec["gates"]
    if coordinate == "relative_to_all":
        return gates["relative_to_all_group_block_minimum_observations"]
    if coordinate == "relative_rank":
        return gates["relative_rank_denominator_block_minimum_observations"]
    return gates["absolute_group_block_minimum_observations"]


def complete_support_audit(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for task in _tasks(spec):
        task_audit: dict[str, Any] = {}
        predictor = task["field"]
        response = _response_name(predictor, task["horizon"])
        controls = _controls(spec, task["coordinate"])
        required = [predictor, response, *controls]
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, block_name, task["horizon"])
            group_audit: dict[str, Any] = {}
            for group_name, group in _analysis_groups(frame, task["coordinate"]):
                clean = group[required].replace([np.inf, -np.inf], np.nan).dropna()
                nondegenerate = {field: bool(clean[field].nunique(dropna=True) > 1) for field in required}
                n = int(len(clean))
                if n < _minimum_support(spec, task["coordinate"]):
                    raise MinuteDefenseDynamicsError(
                        f"support failed: {task['name']}:{block_name}:{group_name}:{n}"
                    )
                if not all(nondegenerate.values()):
                    raise MinuteDefenseDynamicsError(
                        f"nondegeneracy failed: {task['name']}:{block_name}:{group_name}"
                    )
                group_audit[group_name] = {"observations": n, "nondegenerate": nondegenerate}
            task_audit[block_name] = group_audit
        audit[task["name"]] = task_audit
    return audit


def _estimate_task(
    panel: pd.DataFrame, spec: dict[str, Any], task: dict[str, Any]
) -> dict[str, Any]:
    predictor = task["field"]
    response = _response_name(predictor, task["horizon"])
    controls = _controls(spec, task["coordinate"])
    blocks: dict[str, Any] = {}
    for block_name in BLOCK_NAMES:
        frame = _block_frame(panel, spec, block_name, task["horizon"])
        by_group: dict[str, Any] = {}
        for group_name, group in _analysis_groups(frame, task["coordinate"]):
            unadjusted, partial, n = partial_rank_correlation(
                group, predictor, response, controls
            )
            if not np.isfinite(unadjusted) or not np.isfinite(partial):
                raise MinuteDefenseDynamicsError(
                    f"estimate failed: {task['name']}:{block_name}:{group_name}"
                )
            by_group[group_name] = {
                "observations": n,
                "unadjusted_spearman": unadjusted,
                "partial_spearman": partial,
            }
        partials = np.asarray([item["partial_spearman"] for item in by_group.values()])
        unadjusted = np.asarray([item["unadjusted_spearman"] for item in by_group.values()])
        blocks[block_name] = {
            "by_group": by_group,
            "median_unadjusted_spearman": float(np.median(unadjusted)),
            "median_partial_rho": float(np.median(partials)),
            "median_absolute_partial_rho": float(np.median(np.abs(partials))),
        }
    return {**task, "controls": controls, "blocks": blocks}


def _sign_support(task: dict[str, Any], block_name: str, sign: int) -> int:
    values = [
        item["partial_spearman"]
        for item in task["blocks"][block_name]["by_group"].values()
    ]
    return int(np.sum(np.sign(np.asarray(values, dtype=float)) == sign))


def _evaluate(spec: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    primary = diagnostics["absolute_primary_h1"]
    block_a = primary["blocks"][BLOCK_NAMES[0]]
    block_b = primary["blocks"][BLOCK_NAMES[1]]
    learned_sign = int(np.sign(block_a["median_partial_rho"]))
    checks: dict[str, bool] = {
        "h1_nonzero_block_a_sign": learned_sign != 0,
        "h1_block_a_effect": block_a["median_absolute_partial_rho"]
        >= gates["h1_primary_median_absolute_partial_rho_minimum"],
        "h1_block_b_effect": block_b["median_absolute_partial_rho"]
        >= gates["h1_primary_median_absolute_partial_rho_minimum"],
        "h1_block_b_sign": int(np.sign(block_b["median_partial_rho"])) == learned_sign,
        "h1_block_a_sign_support": _sign_support(primary, BLOCK_NAMES[0], learned_sign)
        >= gates["h1_primary_group_sign_support_minimum_of_8"],
        "h1_block_b_sign_support": _sign_support(primary, BLOCK_NAMES[1], learned_sign)
        >= gates["h1_primary_group_sign_support_minimum_of_8"],
        "h1_block_b_magnitude": block_b["median_absolute_partial_rho"]
        >= gates["h1_block_b_to_block_a_absolute_magnitude_ratio_minimum"]
        * block_a["median_absolute_partial_rho"],
    }
    shape_names = [name for name in diagnostics if name.startswith("h1_shape__")]
    for name in shape_names:
        task = diagnostics[name]
        for block_name in BLOCK_NAMES:
            block = task["blocks"][block_name]
            checks[f"{name}:{block_name}:effect"] = block["median_absolute_partial_rho"] \
                >= gates["h1_shape_neighbor_median_absolute_partial_rho_minimum"]
            checks[f"{name}:{block_name}:sign"] = \
                int(np.sign(block["median_partial_rho"])) == learned_sign
            checks[f"{name}:{block_name}:sign_support"] = \
                _sign_support(task, block_name, learned_sign) \
                >= gates["h1_shape_neighbor_group_sign_support_minimum_of_8"]
    for name, support_gate in (
        ("h1_relative_to_all", "h1_relative_to_all_sign_support_minimum_of_6"),
        ("h1_relative_rank", "h1_relative_rank_sign_support_minimum_of_2"),
    ):
        task = diagnostics[name]
        for block_name in BLOCK_NAMES:
            block = task["blocks"][block_name]
            checks[f"{name}:{block_name}:effect"] = block["median_absolute_partial_rho"] \
                >= gates["h1_relative_median_absolute_partial_rho_minimum"]
            checks[f"{name}:{block_name}:sign"] = \
                int(np.sign(block["median_partial_rho"])) == learned_sign
            checks[f"{name}:{block_name}:sign_support"] = \
                _sign_support(task, block_name, learned_sign) >= gates[support_gate]
    for horizon in (3, 5):
        name = f"absolute_primary_h{horizon}"
        task = diagnostics[name]
        for block_name in BLOCK_NAMES:
            block = task["blocks"][block_name]
            checks[f"{name}:{block_name}:effect"] = block["median_absolute_partial_rho"] \
                >= gates["h3_h5_median_absolute_partial_rho_minimum"]
            checks[f"{name}:{block_name}:sign"] = \
                int(np.sign(block["median_partial_rho"])) == learned_sign
            checks[f"{name}:{block_name}:sign_support"] = \
                _sign_support(task, block_name, learned_sign) \
                >= gates["h3_h5_group_sign_support_minimum_of_8"]
    return {
        "learned_block_a_sign": learned_sign,
        "checks": checks,
        "state_dynamic_gate_pass": bool(all(checks.values())),
    }


def analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    support = complete_support_audit(panel, spec)
    diagnostics = {task["name"]: _estimate_task(panel, spec, task) for task in _tasks(spec)}
    decision = _evaluate(spec, diagnostics)
    return support, diagnostics, decision


def _render_report(result: dict[str, Any]) -> str:
    diagnostics = result["state_diagnostics"]
    decision = result["temporal_decision"]
    lines = [
        "# MKT-MIN-DEF-DYN-001 VWAP defense/recovery state dynamics",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        "- Future field read: accepted VWAP defense/recovery state only.",
        "- Future price return, volatility, industry/stock state, strategy fields, raw minutes, failed roles, post-2023 data, and CY-011 read: **none**.",
        "- Both blocks are reused exploratory evidence, not untouched confirmation.",
        "- A pass would be a state dynamic only, not support, accumulation, prediction, timing, habitat, causality, or a rule.",
        "",
        "## Primary and neighboring horizons",
        "",
        "| Horizon | Block A unadjusted | Block A partial | Block B unadjusted | Block B partial |",
        "|---:|---:|---:|---:|---:|",
    ]
    for horizon in (1, 3, 5):
        task = diagnostics[f"absolute_primary_h{horizon}"]
        a = task["blocks"][BLOCK_NAMES[0]]
        b = task["blocks"][BLOCK_NAMES[1]]
        lines.append(
            f"| {horizon} | {a['median_unadjusted_spearman']:.3f} | "
            f"{a['median_partial_rho']:.3f} | {b['median_unadjusted_spearman']:.3f} | "
            f"{b['median_partial_rho']:.3f} |"
        )
    lines.extend([
        "",
        "## H=1 shape and relative challenges",
        "",
        "| Challenge | Block A partial | Block B partial |",
        "|---|---:|---:|",
    ])
    for name, task in diagnostics.items():
        if not name.startswith("h1_") or name == "absolute_primary_h1":
            continue
        a = task["blocks"][BLOCK_NAMES[0]]["median_partial_rho"]
        b = task["blocks"][BLOCK_NAMES[1]]["median_partial_rho"]
        lines.append(f"| `{name}` | {a:.3f} | {b:.3f} |")
    failed = [name for name, passed in decision["checks"].items() if not passed]
    lines.extend([
        "",
        "## Frozen decision",
        "",
        f"- Learned block-A sign: `{decision['learned_block_a_sign']}`",
        f"- All-required state dynamic gate: `{'PASS' if decision['state_dynamic_gate_pass'] else 'FAIL'}`",
        f"- Failed checks: `{', '.join(failed) if failed else 'none'}`",
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
    support, diagnostics, decision = analyze(panel, spec)

    horizons = [1, 3, 5]
    state_fields = [
        *_absolute_fields(spec),
        spec["fields"]["relative_to_all"],
        spec["fields"]["relative_rank"],
    ]
    generated_controls = [_relative_control_name(field) for field in spec["fields"]["controls_pit"]]
    future_fields = [
        _response_name(field, horizon)
        for horizon in horizons
        for field in state_fields
    ]
    time_fields = [
        item
        for horizon in horizons
        for item in (_future_date_name(horizon), _response_available_name(horizon))
    ]
    output = panel[[
        *KEYS, "available_at", "hard_valid", *_source_fields(spec), *generated_controls,
        *time_fields, *future_fields,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    for horizon in horizons:
        field = _future_date_name(horizon)
        output[field] = output[field].dt.strftime("%Y-%m-%d")
    output["available_at"] = output["available_at"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    status = (
        "COMPLETE_STATE_DYNAMIC_PASS"
        if decision["state_dynamic_gate_pass"]
        else "COMPLETE_STATE_DYNAMIC_FAIL"
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "usefulness_claim": "NONE",
        "cross_day_support_claim": "NONE",
        "participant_accumulation_claim": "NONE",
        "future_market_state_fields_read": ["vwap_defense_recovery"],
        "future_price_return_fields_read": [],
        "future_volatility_fields_read": [],
        "future_industry_or_stock_state_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_minute_roles_read": [],
        "raw_minute_rows_read": False,
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "source_rows": int(len(source)),
            "groups": int(source.groupby(GROUP_KEYS).ngroups),
            "first_predictor_date": str(source["trade_date"].min().date()),
            "last_predictor_date": str(source["trade_date"].max().date()),
            "last_h1_response_date": str(panel[_future_date_name(1)].max().date()),
        },
        "complete_support_audit": support,
        "state_diagnostics": diagnostics,
        "temporal_decision": decision,
        "confirmation_status": "NO_UNTOUCHED_CONFIRMATION_REUSED_PRE2024_BLOCKS",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "mechanism_panel_sha256": spec["inputs"]["mechanism_panel"]["sha256"],
            "mechanism_result_sha256": spec["inputs"]["mechanism_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
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
    print(json.dumps({
        "status": completed["status"],
        "state_dynamic_gate_pass": completed["temporal_decision"]["state_dynamic_gate_pass"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
