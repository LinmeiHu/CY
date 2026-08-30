#!/usr/bin/env python3
"""Construct frozen MKT-MIN-VOL-STATE-001 outcome-blind ordinal states."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-VOL-STATE-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-STATE-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-STATE-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-VOL-STATE-001_state.md"
EXPECTED_SPEC_SHA256 = "bf3c5e7aa5443148a35d2afe2c3588e7b206c6d96b4f22d5cd074bb42b5f27f5"
KEYS = ["trade_date", "market_view", "denominator"]
PATH_STATES = ("RISING", "FALLING", "FLAT")
LEVEL_STATES = ("LOW_LEVEL", "MIDDLE_LEVEL", "HIGH_LEVEL")


class MinuteVolatilityStateError(RuntimeError):
    """Fail-closed state construction error."""


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
        raise MinuteVolatilityStateError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_STATE_RESULT":
        raise MinuteVolatilityStateError("spec is not frozen before result")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name in ("path_panel", "path_result", "volatility_panel", "volatility_result", "geometry_result"):
        entry = spec["inputs"][name]
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise MinuteVolatilityStateError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_results(paths: dict[str, Path]) -> None:
    path_result = json.loads(paths["path_result"].read_text(encoding="utf-8"))
    if path_result["diagnostics"]["minimal_panel"]["accepted_roles"] != [
        "minute_realized_volatility__ordinal_progression"
    ]:
        raise MinuteVolatilityStateError("sole accepted path identity mismatch")
    vol_result = json.loads(paths["volatility_result"].read_text(encoding="utf-8"))
    if "realized_volatility" not in vol_result["minimal_panel"]["accepted_roles"]:
        raise MinuteVolatilityStateError("daily volatility level is not accepted")
    geometry = json.loads(paths["geometry_result"].read_text(encoding="utf-8"))
    if geometry["status"] != "COMPLETE_DISTINCT_PATH_COORDINATE":
        raise MinuteVolatilityStateError("external geometry prerequisite failed")


def _local_timestamp(series: pd.Series, naive_local: bool) -> pd.Series:
    parsed = pd.to_datetime(series, errors="raise")
    if naive_local:
        if parsed.dt.tz is not None:
            raise MinuteVolatilityStateError("expected naive local path timestamp")
        return parsed.dt.tz_localize("Asia/Shanghai")
    if parsed.dt.tz is None:
        raise MinuteVolatilityStateError("expected offset-aware volatility timestamp")
    return parsed.dt.tz_convert("Asia/Shanghai")


def load_bound_inputs(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_results(paths)
    fields = spec["path_fields"]
    path_columns = [*KEYS, "available_at", "hard_valid", *fields.values()]
    vol_columns = [*KEYS, "decision_at", "available_at", "view_valid", spec["level_context"]["field"]]
    path = pd.read_csv(paths["path_panel"], usecols=path_columns)
    vol = pd.read_csv(paths["volatility_panel"], usecols=vol_columns)
    for name, frame in (("path", path), ("volatility", vol)):
        if frame.duplicated(KEYS).any():
            raise MinuteVolatilityStateError(f"duplicate {name} keys")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if not path["hard_valid"].astype(bool).all() or not vol["view_valid"].astype(bool).all():
        raise MinuteVolatilityStateError("invalid source row entered state construction")

    start = pd.Timestamp(spec["inputs"]["date_start"])
    end = pd.Timestamp(spec["inputs"]["date_end"])
    path = path.loc[path["trade_date"].between(start, end)].copy()
    vol = vol.loc[vol["trade_date"].between(start, end)].copy()
    expected = spec["population"]["expected_rows"]
    if len(path) != expected or len(vol) != expected:
        raise MinuteVolatilityStateError("source population mismatch")
    path_time = _local_timestamp(path["available_at"], naive_local=True)
    vol_time = _local_timestamp(vol["available_at"], naive_local=False)
    vol_decision = _local_timestamp(vol["decision_at"], naive_local=False)
    if not (path_time.dt.strftime("%H:%M:%S") == "15:30:00").all():
        raise MinuteVolatilityStateError("path is not available at exact 15:30")
    if not (vol_time.dt.strftime("%H:%M:%S") == "15:00:00").all() or (vol_time > vol_decision).any():
        raise MinuteVolatilityStateError("daily level availability contract failed")

    path = path.rename(columns={"available_at": "available_at_path"})
    vol = vol.rename(columns={"available_at": "available_at_volatility",
                              "decision_at": "decision_at_volatility"})
    merged = path.merge(vol, on=KEYS, how="outer", indicator=True, validate="one_to_one")
    if not (merged["_merge"] == "both").all():
        raise MinuteVolatilityStateError("path/volatility key-set mismatch")
    merged = merged.drop(columns="_merge")
    counts = merged.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != spec["gates"]["exact_groups"] or not (
        counts == spec["population"]["expected_rows_per_group"]
    ).all():
        raise MinuteVolatilityStateError("exact group population mismatch")
    if set(merged["market_view"]) != set(spec["population"]["views"]):
        raise MinuteVolatilityStateError("market view identity mismatch")
    if set(merged["denominator"]) != set(spec["population"]["denominators"]):
        raise MinuteVolatilityStateError("denominator identity mismatch")
    merged["state_available_at"] = merged["trade_date"].dt.strftime("%Y-%m-%dT15:30:00+08:00")
    return merged.sort_values(KEYS).reset_index(drop=True)


def path_state(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value > 0.0:
        return "RISING"
    if value < 0.0:
        return "FALLING"
    return "FLAT"


def level_state(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value <= 0.20:
        return "LOW_LEVEL"
    if value >= 0.80:
        return "HIGH_LEVEL"
    return "MIDDLE_LEVEL"


def cohen_kappa(left: pd.Series, right: pd.Series) -> float:
    clean = pd.DataFrame({"left": left, "right": right})
    clean = clean.loc[clean["left"].isin(PATH_STATES) & clean["right"].isin(PATH_STATES)]
    if len(clean) == 0:
        return float("nan")
    observed = float((clean["left"] == clean["right"]).mean())
    expected = sum(
        float((clean["left"] == state).mean()) * float((clean["right"] == state).mean())
        for state in PATH_STATES
    )
    if expected >= 1.0:
        return float("nan")
    return float((observed - expected) / (1.0 - expected))


def macro_jaccard(left: pd.Series, right: pd.Series) -> float:
    clean = pd.DataFrame({"left": left, "right": right})
    clean = clean.loc[clean["left"].isin(PATH_STATES) & clean["right"].isin(PATH_STATES)]
    scores: list[float] = []
    for state in PATH_STATES:
        intersection = int(((clean["left"] == state) & (clean["right"] == state)).sum())
        union = int(((clean["left"] == state) | (clean["right"] == state)).sum())
        if union == 0:
            return float("nan")
        scores.append(intersection / union)
    return float(np.mean(scores))


def completed_run_lengths(states: pd.Series) -> dict[str, list[int]]:
    values = states.astype(str).tolist()
    runs: list[tuple[str, int]] = []
    for value in values:
        if not runs or runs[-1][0] != value:
            runs.append((value, 1))
        else:
            state, length = runs[-1]
            runs[-1] = (state, length + 1)
    completed = runs[1:-1] if len(runs) >= 3 else []
    return {state: [length for run_state, length in completed if run_state == state] for state in PATH_STATES}


def transition_distribution(states: pd.Series) -> np.ndarray:
    values = states.astype(str).tolist()
    counts = np.zeros((len(PATH_STATES), len(PATH_STATES)), dtype=float)
    positions = {state: index for index, state in enumerate(PATH_STATES)}
    for left, right in zip(values[:-1], values[1:]):
        if left in positions and right in positions:
            counts[positions[left], positions[right]] += 1.0
    total = float(counts.sum())
    return counts.ravel() / total if total > 0.0 else np.full(9, np.nan)


def _construct_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    output = panel.copy()
    for role, field in spec["path_fields"].items():
        output[f"{role}_state"] = pd.to_numeric(output[field], errors="coerce").map(path_state)
    output["daily_level_state"] = pd.to_numeric(
        output[spec["level_context"]["field"]], errors="coerce"
    ).map(level_state)
    output["primary_by_level_state"] = output["primary_state"] + "__" + output["daily_level_state"]
    return output


def _coverage_recurrence(states: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    years = set(spec["population"]["cell_years"])
    minimum_valid = spec["gates"]["group_year_minimum_valid_observations"]
    minimum_state = spec["gates"]["state_group_year_minimum_observations"]
    minimum_joint = spec["gates"]["path_by_level_group_year_minimum_observations"]
    fields = [*spec["path_fields"].values(), spec["level_context"]["field"]]
    valid_cells: dict[str, Any] = {}
    state_cells: dict[str, int] = {}
    joint_cells: dict[str, int] = {}
    valid_pass = state_pass = joint_pass = True
    work = states.assign(year=states["trade_date"].dt.year)
    for (view, denominator, year), group in work.groupby(["market_view", "denominator", "year"], sort=True):
        if int(year) not in years:
            continue
        key = f"{view}:{denominator}:{year}"
        counts = {
            field: int(pd.to_numeric(group[field], errors="coerce").replace([np.inf, -np.inf], np.nan).notna().sum())
            for field in fields
        }
        valid_cells[key] = counts
        valid_pass &= all(value >= minimum_valid for value in counts.values())
        for state in PATH_STATES:
            count = int((group["primary_state"] == state).sum())
            state_cells[f"{key}:{state}"] = count
            state_pass &= count >= minimum_state
        for path_label in PATH_STATES:
            for level_label in LEVEL_STATES:
                count = int((group["primary_by_level_state"] == f"{path_label}__{level_label}").sum())
                joint_cells[f"{key}:{path_label}:{level_label}"] = count
                joint_pass &= count >= minimum_joint
    expected_cells = spec["gates"]["exact_groups"] * len(years)
    valid_pass &= len(valid_cells) == expected_cells
    return {
        "valid_cells": valid_cells,
        "state_counts": state_cells,
        "path_by_level_counts": joint_cells,
        "valid_cell_gate_pass": bool(valid_pass),
        "state_recurrence_gate_pass": bool(state_pass),
        "path_by_level_gate_pass": bool(joint_pass),
    }


def _agreement(states: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    overall = True
    for neighbor in ("neighbor_all_pairs", "neighbor_rank_time"):
        groups: dict[str, Any] = {}
        kappas: list[float] = []
        jaccards: list[float] = []
        for (view, denominator), group in states.groupby(["market_view", "denominator"], sort=True):
            kappa = cohen_kappa(group["primary_state"], group[f"{neighbor}_state"])
            jaccard = macro_jaccard(group["primary_state"], group[f"{neighbor}_state"])
            groups[f"{view}:{denominator}"] = {"cohen_kappa": kappa, "macro_jaccard": jaccard}
            kappas.append(kappa)
            jaccards.append(jaccard)
        kappa_values = np.asarray(kappas, dtype=float)
        jaccard_values = np.asarray(jaccards, dtype=float)
        if not np.isfinite(kappa_values).all() or not np.isfinite(jaccard_values).all():
            raise MinuteVolatilityStateError("nonfinite state agreement")
        passes = {
            "kappa_median": bool(np.median(kappa_values) >= spec["gates"]["neighbor_state_kappa_median_minimum"]),
            "kappa_minimum": bool(np.min(kappa_values) >= spec["gates"]["neighbor_state_kappa_group_minimum"]),
            "jaccard_median": bool(np.median(jaccard_values) >= spec["gates"]["neighbor_macro_jaccard_median_minimum"]),
            "jaccard_minimum": bool(np.min(jaccard_values) >= spec["gates"]["neighbor_macro_jaccard_group_minimum"]),
        }
        passes["all"] = bool(all(passes.values()))
        overall &= passes["all"]
        output[neighbor] = {
            "groups": groups,
            "median_kappa": float(np.median(kappa_values)),
            "minimum_kappa": float(np.min(kappa_values)),
            "median_macro_jaccard": float(np.median(jaccard_values)),
            "minimum_macro_jaccard": float(np.min(jaccard_values)),
            "gates": passes,
        }
    output["all_neighbors_gate_pass"] = bool(overall)
    return output


def _dwell_and_transitions(states: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    dwell: dict[str, Any] = {}
    transitions: dict[str, Any] = {}
    primary_run_pass = dwell_ratio_pass = transition_pass = True
    transition_values: dict[str, list[float]] = {"neighbor_all_pairs": [], "neighbor_rank_time": []}
    for (view, denominator), group in states.groupby(["market_view", "denominator"], sort=True):
        ordered = group.sort_values("trade_date")
        key = f"{view}:{denominator}"
        runs = {
            role: completed_run_lengths(ordered[f"{role}_state"])
            for role in ("primary", "neighbor_all_pairs", "neighbor_rank_time")
        }
        dwell[key] = {}
        for state in PATH_STATES:
            primary_lengths = runs["primary"][state]
            count = len(primary_lengths)
            primary_run_pass &= count >= spec["gates"]["state_group_minimum_completed_runs"]
            primary_median = float(np.median(primary_lengths)) if primary_lengths else float("nan")
            state_diag: dict[str, Any] = {
                "primary_completed_runs": count,
                "primary_median_dwell": primary_median,
            }
            for neighbor in ("neighbor_all_pairs", "neighbor_rank_time"):
                lengths = runs[neighbor][state]
                neighbor_median = float(np.median(lengths)) if lengths else float("nan")
                ratio = neighbor_median / primary_median if primary_median > 0.0 else float("nan")
                ratio_ok = bool(
                    np.isfinite(ratio)
                    and spec["gates"]["neighbor_to_primary_median_dwell_ratio_minimum"] <= ratio
                    <= spec["gates"]["neighbor_to_primary_median_dwell_ratio_maximum"]
                )
                dwell_ratio_pass &= ratio_ok
                state_diag[neighbor] = {
                    "completed_runs": len(lengths),
                    "median_dwell": neighbor_median,
                    "median_dwell_ratio": ratio,
                    "gate_pass": ratio_ok,
                }
            dwell[key][state] = state_diag

        primary_transition = transition_distribution(ordered["primary_state"])
        transitions[key] = {}
        for neighbor in ("neighbor_all_pairs", "neighbor_rank_time"):
            neighbor_transition = transition_distribution(ordered[f"{neighbor}_state"])
            distance = float(0.5 * np.abs(primary_transition - neighbor_transition).sum())
            transitions[key][neighbor] = {"total_variation": distance}
            transition_values[neighbor].append(distance)

    summary: dict[str, Any] = {}
    for neighbor, values in transition_values.items():
        array = np.asarray(values, dtype=float)
        median = float(np.median(array))
        maximum = float(np.max(array))
        gate = bool(
            median <= spec["gates"]["transition_total_variation_median_maximum"]
            and maximum <= spec["gates"]["transition_total_variation_group_maximum"]
        )
        transition_pass &= gate
        summary[neighbor] = {
            "median_total_variation": median,
            "maximum_total_variation": maximum,
            "gate_pass": gate,
        }
    dwell["gates"] = {
        "primary_run_support": bool(primary_run_pass),
        "neighbor_dwell_ratio": bool(dwell_ratio_pass),
        "all": bool(primary_run_pass and dwell_ratio_pass),
    }
    transitions["summary"] = summary
    transitions["all_neighbors_gate_pass"] = bool(transition_pass)
    return dwell, transitions


def _render_report(result: dict[str, Any]) -> str:
    coverage = result["coverage_recurrence"]
    agreement = result["state_agreement"]
    transition = result["transitions"]
    lines = [
        "# MKT-MIN-VOL-STATE-001 ordinal path states",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Rows: {result['population']['rows']:,}; {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Current state is available at 15:30; dwell/transitions are later post-state attribution, never entry predictors.",
        "- Raw minutes, failed representations, future returns, strategy outcomes, and CY-011 read: **none**.",
        "- Rising/falling/flat are ordinal path labels, not economic expansion/contraction or trading states.",
        "",
        "## Core gates",
        "",
        f"- Valid group/year cells: {'PASS' if coverage['valid_cell_gate_pass'] else 'FAIL'}.",
        f"- Primary state recurrence: {'PASS' if coverage['state_recurrence_gate_pass'] else 'FAIL'}.",
        f"- Nine-cell path-by-level recurrence: {'PASS' if coverage['path_by_level_gate_pass'] else 'FAIL'}.",
        f"- Completed-run/dwell support: {'PASS' if result['dwell']['gates']['all'] else 'FAIL'}.",
        "",
        "## Definition-neighbor state agreement",
        "",
        "| Neighbor | Median kappa | Minimum kappa | Median macro Jaccard | Minimum macro Jaccard | Gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for neighbor in ("neighbor_all_pairs", "neighbor_rank_time"):
        item = agreement[neighbor]
        lines.append(
            f"| `{neighbor}` | {item['median_kappa']:.3f} | {item['minimum_kappa']:.3f} | "
            f"{item['median_macro_jaccard']:.3f} | {item['minimum_macro_jaccard']:.3f} | "
            f"{'PASS' if item['gates']['all'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Transition stability",
        "",
        "| Neighbor | Median total variation | Maximum total variation | Gate |",
        "|---|---:|---:|---|",
    ])
    for neighbor in ("neighbor_all_pairs", "neighbor_rank_time"):
        item = transition["summary"][neighbor]
        lines.append(
            f"| `{neighbor}` | {item['median_total_variation']:.3f} | {item['maximum_total_variation']:.3f} | "
            f"{'PASS' if item['gate_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel = load_bound_inputs(spec)
    states = _construct_states(panel, spec)
    coverage = _coverage_recurrence(states, spec)
    agreement = _agreement(states, spec)
    dwell, transitions = _dwell_and_transitions(states, spec)
    passes = {
        "valid_cells": coverage["valid_cell_gate_pass"],
        "state_recurrence": coverage["state_recurrence_gate_pass"],
        "path_by_level_recurrence": coverage["path_by_level_gate_pass"],
        "state_agreement": agreement["all_neighbors_gate_pass"],
        "dwell": dwell["gates"]["all"],
        "transitions": transitions["all_neighbors_gate_pass"],
    }
    passes["all"] = bool(all(passes.values()))
    status = "COMPLETE_EXACT_RECURRENT_STATES_FROZEN" if passes["all"] else "COMPLETE_EXACT_STATE_ARCHITECTURE_FAIL"

    output = states.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "population": {
            "rows": int(len(states)),
            "groups": int(states.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(states["trade_date"].min().date()),
            "last_date": str(states["trade_date"].max().date()),
        },
        "coverage_recurrence": coverage,
        "state_agreement": agreement,
        "dwell": dwell,
        "transitions": transitions,
        "gates": passes,
        "raw_minute_rows_read": 0,
        "failed_representation_fields_read": [],
        "future_market_outcomes_read": [],
        "strategy_or_outcome_fields_read": [],
        "cy011_read": False,
        "mechanism_claim": "DESCRIPTIVE_ORDINAL_PATH_STATES" if passes["all"] else "NONE",
        "usefulness_claim": "NONE",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "path_panel_sha256": spec["inputs"]["path_panel"]["sha256"],
            "path_result_sha256": spec["inputs"]["path_result"]["sha256"],
            "volatility_panel_sha256": spec["inputs"]["volatility_panel"]["sha256"],
            "volatility_result_sha256": spec["inputs"]["volatility_result"]["sha256"],
            "geometry_result_sha256": spec["inputs"]["geometry_result"]["sha256"],
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
        "gates": completed["gates"],
        "agreement": {
            key: completed["state_agreement"][key] for key in ("neighbor_all_pairs", "neighbor_rank_time")
        },
        "transition_summary": completed["transitions"]["summary"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
