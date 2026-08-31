#!/usr/bin/env python3
"""Run the frozen formation-depth tail-risk mechanism attribution."""

from __future__ import annotations

import hashlib
import json
import platform
import resource
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-ATTR-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_panel.csv"
GEOMETRY_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_geometry_audit.csv"
RESPONSE_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_response_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-ATTR-001_attribution.md"
EXPECTED_SPEC_SHA256 = "676032c509384ae63b237141d5dbbf395c051c04100529ee02dcafe4989cdce7"


class AttributionError(RuntimeError):
    """Fail-closed attribution-contract error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise AttributionError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_EXTENDED_CONTROL_RESPONSE_ESTIMATES"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_H1_H3_H5_DOWNSIDE_RESPONSE_ONLY"
    ):
        raise AttributionError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise AttributionError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise AttributionError("prohibited boundary changed")
    economic = json.loads(
        _resolve(spec["inputs"]["economic_result"]["path"]).read_text(encoding="utf-8")
    )
    role = economic["classifications"].get(spec["activation"]["required_role"], {})
    if role.get("status") != spec["activation"]["required_status"]:
        raise AttributionError("accepted formation-depth response is not activated")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise AttributionError("system memory headroom below frozen floor")
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise AttributionError("process peak RSS ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60:
        raise AttributionError("wall-clock ceiling breached")


def _median(values: pd.Series | np.ndarray | list[float]) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _rank(frame: pd.DataFrame) -> np.ndarray:
    return frame.rank(method="average").to_numpy(dtype=float)


def _residual(y: np.ndarray, controls: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(y)), controls])
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    return y - design @ coefficients


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(frame: pd.DataFrame, x: str, y: str) -> tuple[int, float]:
    valid = frame[[x, y]].dropna()
    if len(valid) < 3 or valid[x].nunique() < 2 or valid[y].nunique() < 2:
        return len(valid), float("nan")
    ranks = _rank(valid[[x, y]])
    return len(valid), _corr(ranks[:, 0], ranks[:, 1])


def _adjusted_rank_r2(
    frame: pd.DataFrame, target: str, controls: list[str]
) -> tuple[int, float, float]:
    valid = frame[[target, *controls]].dropna()
    n = len(valid)
    p = len(controls)
    if n <= p + 2 or valid[target].nunique() < 2:
        return n, float("nan"), float("nan")
    ranks = _rank(valid[[target, *controls]])
    y = ranks[:, 0]
    residual = _residual(y, ranks[:, 1:])
    total = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1 - np.sum(residual**2) / total) if total > 0 else float("nan")
    adjusted = float(1 - (1 - r2) * (n - 1) / (n - p - 1))
    return n, r2, adjusted


def _partial_rank(
    frame: pd.DataFrame, target: str, outcome: str, controls: list[str]
) -> tuple[int, float]:
    valid = frame[[target, outcome, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), float("nan")
    ranks = _rank(valid[[target, outcome, *controls]])
    target_residual = _residual(ranks[:, 0], ranks[:, 2:])
    outcome_residual = _residual(ranks[:, 1], ranks[:, 2:])
    return len(valid), _corr(target_residual, outcome_residual)


def _tail_residual_gap(
    frame: pd.DataFrame,
    target_pit: str,
    outcome: str,
    controls: list[str],
    low_maximum: float,
    high_minimum: float,
) -> tuple[int, int, int, float]:
    valid = frame[[target_pit, outcome, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), 0, 0, float("nan")
    control_ranks = _rank(valid[controls])
    response_residual = _residual(valid[outcome].to_numpy(dtype=float), control_ranks)
    pit = valid[target_pit].to_numpy(dtype=float)
    low = response_residual[pit <= low_maximum]
    high = response_residual[pit >= high_minimum]
    gap = float(np.mean(high) - np.mean(low)) if len(low) and len(high) else float("nan")
    return len(valid), len(low), len(high), gap


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    target = spec["target"]
    controls = spec["controls"]
    responses = [spec["response"]["primary"], *spec["response"]["neighbors"]]
    economic_columns = [
        *keys,
        target["absolute"],
        target["pit"],
        controls["original_discovery"],
        controls["original_volatility"],
        "event_year",
        "session_ordinal",
        *responses,
    ]
    economic = pd.read_csv(
        _resolve(spec["inputs"]["economic_panel"]["path"]),
        usecols=economic_columns,
        parse_dates=["trade_date"],
    )
    if len(economic) != spec["activation"]["expected_economic_rows"]:
        raise AttributionError("economic panel row count changed")
    if economic[keys].duplicated().any():
        raise AttributionError("economic panel key is not unique")
    risk = pd.read_csv(
        _resolve(spec["inputs"]["risk_panel"]["path"]),
        usecols=[
            *keys,
            "available_at",
            controls["central_direction"],
            controls["central_direction_pit"],
        ],
        parse_dates=["trade_date"],
    ).rename(columns={"available_at": "risk_available_at"})
    minute = pd.read_csv(
        _resolve(spec["inputs"]["minute_panel"]["path"]),
        usecols=[
            *keys,
            "available_at",
            controls["open_close_return"],
            controls["intraday_range"],
        ],
        parse_dates=["trade_date"],
    ).rename(columns={"available_at": "minute_available_at"})
    if risk[keys].duplicated().any() or minute[keys].duplicated().any():
        raise AttributionError("control panel key is not unique")
    panel = economic.merge(risk, on=keys, how="left", validate="one_to_one").merge(
        minute, on=keys, how="left", validate="one_to_one"
    )
    if len(panel) != len(economic):
        raise AttributionError("attribution join changed economic row count")
    minute_clock = pd.to_datetime(panel["minute_available_at"], errors="coerce")
    if minute_clock.isna().any() or not (
        (minute_clock.dt.hour == 15) & (minute_clock.dt.minute == 30)
    ).all():
        raise AttributionError("minute-control availability is not exactly 15:30")
    risk_clock = pd.to_datetime(panel["risk_available_at"], errors="coerce")
    if not (
        (risk_clock.dropna().dt.hour < 15)
        | (
            (risk_clock.dropna().dt.hour == 15)
            & (risk_clock.dropna().dt.minute <= 30)
        )
    ).all():
        raise AttributionError("risk control is available after the joint local clock")
    panel["available_at"] = minute_clock.dt.strftime("%Y-%m-%dT%H:%M:%S")
    primary_columns = [target["pit"], spec["response"]["primary"]] + controls[
        "all_five_primary"
    ]
    complete = panel[primary_columns].dropna()
    groups = panel[keys[1:]].drop_duplicates()
    if len(complete) < spec["activation"]["minimum_complete_joint_rows"]:
        raise AttributionError("complete joint support below frozen floor")
    if len(groups) != spec["activation"]["expected_groups"]:
        raise AttributionError("cell count changed")
    if panel["event_year"].max() > 2023:
        raise AttributionError("post-2023 row reached attribution panel")
    support = {
        "economic_rows": len(economic),
        "joined_rows": len(panel),
        "complete_primary_rows": len(complete),
        "groups": len(groups),
        "years": sorted(int(value) for value in panel["event_year"].unique()),
        "minimum_complete_rows_per_cell": int(
            panel.groupby(keys[1:], sort=True)[primary_columns]
            .apply(lambda group: len(group.dropna()))
            .min()
        ),
        "joint_available_at": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
    }
    columns = [
        *keys,
        "available_at",
        "event_year",
        "session_ordinal",
        target["absolute"],
        target["pit"],
        controls["original_discovery"],
        controls["original_volatility"],
        controls["central_direction"],
        controls["central_direction_pit"],
        controls["open_close_return"],
        controls["intraday_range"],
        *responses,
    ]
    return panel[columns].sort_values(keys).reset_index(drop=True), support


def _geometry_audit(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    target = spec["target"]
    controls = spec["controls"]
    pairwise_controls = {
        "original_discovery": controls["original_discovery"],
        "original_volatility": controls["original_volatility"],
        "central_direction": controls["central_direction"],
        "open_close_return": controls["open_close_return"],
        "intraday_range": controls["intraday_range"],
    }
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, str, str, pd.DataFrame]] = []
    for (view, denominator), group in panel.groupby(
        ["market_view", "denominator"], sort=True
    ):
        scopes.append(("cell", f"{view}:{denominator}", view, denominator, group))
        for block, years in spec["geometry_gates"]["blocks"].items():
            scopes.append(
                (
                    "block",
                    block,
                    view,
                    denominator,
                    group[group["event_year"].isin(years)],
                )
            )
    for scope, scope_value, view, denominator, group in scopes:
        for coordinate, target_column in (
            ("absolute", target["absolute"]),
            ("pit", target["pit"]),
        ):
            for control_role, default_column in pairwise_controls.items():
                control_column = (
                    controls["central_direction_pit"]
                    if coordinate == "pit" and control_role == "central_direction"
                    else default_column
                )
                n, rho = _spearman(group, target_column, control_column)
                rows.append(
                    {
                        "audit_type": "pairwise",
                        "scope": scope,
                        "scope_value": scope_value,
                        "market_view": view,
                        "denominator": denominator,
                        "coordinate": coordinate,
                        "target": target_column,
                        "control_role": control_role,
                        "control_column": control_column,
                        "n": n,
                        "spearman": rho,
                        "r2": np.nan,
                        "adjusted_r2": np.nan,
                    }
                )
            n, r2, adjusted = _adjusted_rank_r2(
                group, target_column, controls["all_five_primary"]
            )
            rows.append(
                {
                    "audit_type": "joint_rank_regression",
                    "scope": scope,
                    "scope_value": scope_value,
                    "market_view": view,
                    "denominator": denominator,
                    "coordinate": coordinate,
                    "target": target_column,
                    "control_role": "all_five_primary",
                    "control_column": "|".join(controls["all_five_primary"]),
                    "n": n,
                    "spearman": np.nan,
                    "r2": r2,
                    "adjusted_r2": adjusted,
                }
            )
    return pd.DataFrame(rows).sort_values(
        [
            "audit_type",
            "scope",
            "scope_value",
            "market_view",
            "denominator",
            "coordinate",
            "control_role",
        ]
    ).reset_index(drop=True)


def _response_audit(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    target = spec["target"]
    controls = spec["controls"]["all_five_primary"]
    horizons = [1, 3, 5]
    rows: list[dict[str, Any]] = []

    def append_partial(
        group: pd.DataFrame,
        view: str,
        denominator: str,
        coordinate: str,
        target_column: str,
        horizon: int,
        scope: str,
        scope_value: str,
    ) -> None:
        outcome = f"adverse_mean_log_excursion_h{horizon}"
        n, rho = _partial_rank(group, target_column, outcome, controls)
        rows.append(
            {
                "audit_type": "partial_rank",
                "scope": scope,
                "scope_value": scope_value,
                "market_view": view,
                "denominator": denominator,
                "coordinate": coordinate,
                "horizon": horizon,
                "n": n,
                "partial_rho": rho,
                "low_n": np.nan,
                "high_n": np.nan,
                "tail_residual_gap": np.nan,
            }
        )

    for (view, denominator), group in panel.groupby(
        ["market_view", "denominator"], sort=True
    ):
        group = group.sort_values("trade_date")
        for coordinate, target_column in (
            ("absolute", target["absolute"]),
            ("pit", target["pit"]),
        ):
            for horizon in horizons:
                append_partial(
                    group,
                    view,
                    denominator,
                    coordinate,
                    target_column,
                    horizon,
                    "cell",
                    f"{view}:{denominator}",
                )
        for block, years in spec["geometry_gates"]["blocks"].items():
            append_partial(
                group[group["event_year"].isin(years)],
                view,
                denominator,
                "pit",
                target["pit"],
                3,
                "block",
                block,
            )
        for year in spec["response_gates"]["pit_supported_years"]:
            append_partial(
                group[group["event_year"] == year],
                view,
                denominator,
                "pit",
                target["pit"],
                3,
                "year",
                str(year),
            )
            append_partial(
                group[
                    group["event_year"].isin(
                        [
                            value
                            for value in spec["response_gates"]["pit_supported_years"]
                            if value != year
                        ]
                    )
                ],
                view,
                denominator,
                "pit",
                target["pit"],
                3,
                "leave_one_year_out",
                str(year),
            )
        for horizon in (3, 5):
            for phase in range(horizon):
                append_partial(
                    group[group["session_ordinal"] % horizon == phase],
                    view,
                    denominator,
                    "pit",
                    target["pit"],
                    horizon,
                    "phase",
                    str(phase),
                )
        n, low_n, high_n, gap = _tail_residual_gap(
            group,
            target["pit"],
            spec["response"]["primary"],
            controls,
            target["pit_low_maximum"],
            target["pit_high_minimum"],
        )
        rows.append(
            {
                "audit_type": "tail_residual_gap",
                "scope": "cell",
                "scope_value": f"{view}:{denominator}",
                "market_view": view,
                "denominator": denominator,
                "coordinate": "pit",
                "horizon": 3,
                "n": n,
                "partial_rho": np.nan,
                "low_n": low_n,
                "high_n": high_n,
                "tail_residual_gap": gap,
            }
        )
    return pd.DataFrame(rows).sort_values(
        [
            "audit_type",
            "scope",
            "scope_value",
            "market_view",
            "denominator",
            "coordinate",
            "horizon",
        ]
    ).reset_index(drop=True)


def _evaluate(
    geometry: pd.DataFrame, response: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    geometry_gate = spec["geometry_gates"]
    response_gate = spec["response_gates"]
    cell_pairwise = geometry[
        (geometry["audit_type"] == "pairwise") & (geometry["scope"] == "cell")
    ]
    maximum_pairwise = float(cell_pairwise["spearman"].abs().max())
    cell_joint = geometry[
        (geometry["audit_type"] == "joint_rank_regression")
        & (geometry["scope"] == "cell")
    ]
    median_joint = _median(cell_joint["adjusted_r2"])
    geometry_pass = (
        maximum_pairwise < geometry_gate["maximum_absolute_pairwise_spearman"]
        and median_joint <= geometry_gate["maximum_median_joint_adjusted_rank_r2"]
    )

    partial = response[response["audit_type"] == "partial_rank"]
    primary = partial[
        (partial["scope"] == "cell")
        & (partial["coordinate"] == "pit")
        & (partial["horizon"] == 3)
    ]
    primary_values = primary["partial_rho"].to_numpy(dtype=float)
    median_h3 = _median(primary_values)
    same_sign_cells = int(np.sum(primary_values < 0))
    neighbor_medians = {
        str(horizon): _median(
            partial[
                (partial["scope"] == "cell")
                & (partial["coordinate"] == "pit")
                & (partial["horizon"] == horizon)
            ]["partial_rho"]
        )
        for horizon in (1, 5)
    }
    block_medians = {
        block: _median(
            partial[
                (partial["scope"] == "block")
                & (partial["scope_value"] == block)
            ]["partial_rho"]
        )
        for block in geometry_gate["blocks"]
    }
    year_medians = {
        str(year): _median(
            partial[
                (partial["scope"] == "year")
                & (partial["scope_value"] == str(year))
            ]["partial_rho"]
        )
        for year in response_gate["pit_supported_years"]
    }
    loo_medians = {
        str(year): _median(
            partial[
                (partial["scope"] == "leave_one_year_out")
                & (partial["scope_value"] == str(year))
            ]["partial_rho"]
        )
        for year in response_gate["pit_supported_years"]
    }
    phase_signs: dict[str, list[int]] = {}
    for horizon in (3, 5):
        phase_signs[str(horizon)] = [
            _sign(
                _median(
                    partial[
                        (partial["scope"] == "phase")
                        & (partial["horizon"] == horizon)
                        & (partial["scope_value"] == str(phase))
                    ]["partial_rho"]
                )
            )
            for phase in range(horizon)
        ]
    tail_gap = _median(
        response[response["audit_type"] == "tail_residual_gap"]["tail_residual_gap"]
    )
    response_checks = {
        "primary_size_and_sign": median_h3
        <= -response_gate["minimum_absolute_median_h3_partial_rho"],
        "same_sign_cells": same_sign_cells >= response_gate["minimum_same_sign_cells"],
        "blocks": all(
            value <= -response_gate["minimum_absolute_block_partial_rho"]
            for value in block_medians.values()
        ),
        "years": all(value < 0 for value in year_medians.values()),
        "leave_one_year_out": all(value < 0 for value in loo_medians.values()),
        "neighbors": all(value < 0 for value in neighbor_medians.values()),
        "h3_phases": sum(value < 0 for value in phase_signs["3"])
        >= response_gate["h3_phase_same_sign_minimum"],
        "h5_phases": sum(value < 0 for value in phase_signs["5"])
        >= response_gate["h5_phase_same_sign_minimum"],
        "tail_residual_gap": tail_gap
        <= response_gate["maximum_median_tail_residual_gap"],
    }
    response_pass = all(response_checks.values())
    if not response_pass:
        classification = spec["classification"]["response_fail"]
    elif not geometry_pass:
        classification = spec["classification"]["directness_fail"]
    else:
        classification = spec["classification"]["pass"]
    evaluation = {
        "geometry": {
            "pass": geometry_pass,
            "maximum_absolute_pairwise_spearman": maximum_pairwise,
            "maximum_pairwise_gate": geometry_gate[
                "maximum_absolute_pairwise_spearman"
            ],
            "median_joint_adjusted_rank_r2": median_joint,
            "median_joint_gate": geometry_gate[
                "maximum_median_joint_adjusted_rank_r2"
            ],
            "block_median_joint_adjusted_rank_r2": {
                block: _median(
                    geometry[
                        (geometry["audit_type"] == "joint_rank_regression")
                        & (geometry["scope"] == "block")
                        & (geometry["scope_value"] == block)
                    ]["adjusted_r2"]
                )
                for block in geometry_gate["blocks"]
            },
        },
        "response": {
            "pass": response_pass,
            "checks": response_checks,
            "median_h3_partial_rho": median_h3,
            "same_sign_cells": same_sign_cells,
            "neighbor_median_partial_rho": neighbor_medians,
            "block_median_partial_rho": block_medians,
            "year_median_partial_rho": year_medians,
            "leave_one_year_out_median_partial_rho": loo_medians,
            "phase_signs": phase_signs,
            "median_tail_residual_gap": tail_gap,
        },
    }
    return evaluation, classification


def _write_report(result: dict[str, Any]) -> None:
    geometry = result["evaluation"]["geometry"]
    response = result["evaluation"]["response"]
    checks = "\n".join(
        f"- `{name}`: **{'PASS' if passed else 'FAIL'}**"
        for name, passed in response["checks"].items()
    )
    report = f"""# MKT-FORMDEPTH-ATTR-001 mechanism attribution

## Decision

`{result['classification']}`

This is a same-day market-state attribution result, not a causal claim, entry
predictor, habitat, signal, trade, or strategy rule. The joint information clock
is 15:30 and every response starts on the next exchange session.

## Frozen-support audit

- joined economic rows: {result['support']['joined_rows']:,}
- complete five-control rows: {result['support']['complete_primary_rows']:,}
- minimum complete rows per cell: {result['support']['minimum_complete_rows_per_cell']:,}
- cells: {result['support']['groups']}
- years: {result['support']['years']}

The originally drafted 10,000-row complete-support floor was corrected to 6,500
before any response estimate because the mandatory causal discovery and volatility
controls begin later than the raw panels. No control, response, horizon, gate, or
classification was changed.

## Directness geometry

- maximum absolute same-cell pairwise Spearman: {geometry['maximum_absolute_pairwise_spearman']:.6f}
  (gate < {geometry['maximum_pairwise_gate']:.2f})
- median same-cell joint adjusted rank R2: {geometry['median_joint_adjusted_rank_r2']:.6f}
  (gate <= {geometry['median_joint_gate']:.2f})
- geometry gate: **{'PASS' if geometry['pass'] else 'FAIL'}**

## Extended-control downside response

- median h=3 PIT partial rho: {response['median_h3_partial_rho']:.6f}
- negative cells: {response['same_sign_cells']}/8
- h=1 median partial rho: {response['neighbor_median_partial_rho']['1']:.6f}
- h=5 median partial rho: {response['neighbor_median_partial_rho']['5']:.6f}
- block medians: {response['block_median_partial_rho']}
- supported-year medians: {response['year_median_partial_rho']}
- supported-year leave-one-out medians: {response['leave_one_year_out_median_partial_rho']}
- h=3 phase signs: {response['phase_signs']['3']}
- h=5 phase signs: {response['phase_signs']['5']}
- median controlled high-minus-low PIT-tail residual gap: {response['median_tail_residual_gap']:.6f}

{checks}

The narrower MKT-BREAKOUT-ECON-001 result remains an accurate result under its
pre-frozen discovery/volatility controls. This experiment only determines whether
that association remains incremental after central direction and ordinary same-day
return/range geometry are added. HAB-CHX-FORMDEPTH-001 already found no CHINEXT V1
habitat transfer, so no strategy action follows regardless of this classification.

CY-011, strategy fields, and post-2023 data were not read.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    _resource_guard(spec, started)
    panel, support = _load_panel(spec)
    geometry = _geometry_audit(panel, spec)
    response = _response_audit(panel, spec)
    evaluation, classification = _evaluate(geometry, response, spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    geometry.to_csv(
        GEOMETRY_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    response.to_csv(
        RESPONSE_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_MARKET_MECHANISM_ATTRIBUTION",
        "classification": classification,
        "claim": spec["classification"]["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "joint_information_clock": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
        "support": support,
        "evaluation": evaluation,
        "strategy_fields_read": False,
        "cy011_read": False,
        "post_2023_read": False,
        "habitat_action": "NONE",
        "resource_contract": spec["resource_budget"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "map_sha256": sha256_file(
                _resolve(spec["inputs"]["attribution_map"]["path"])
            ),
            "runner_sha256": sha256_file(Path(__file__)),
            "panel_sha256": sha256_file(PANEL_PATH),
            "geometry_audit_sha256": sha256_file(GEOMETRY_PATH),
            "response_audit_sha256": sha256_file(RESPONSE_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(result)
    _resource_guard(spec, started)
    output_bytes = sum(
        path.stat().st_size
        for path in (PANEL_PATH, GEOMETRY_PATH, RESPONSE_PATH, RESULT_PATH, REPORT_PATH)
    )
    if output_bytes > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise AttributionError("durable-output ceiling breached")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
