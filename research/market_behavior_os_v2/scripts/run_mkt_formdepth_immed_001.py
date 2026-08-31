#!/usr/bin/env python3
"""Estimate the frozen formation-depth trough-immediacy association."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-IMMED-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-IMMED-001_panel.csv"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-IMMED-001_response_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-IMMED-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-IMMED-001_timing.md"
EXPECTED_SPEC_SHA256 = "912021f6df1351dea1a1b69bc3977dfd824b72ab4894f3f2a03821813e30ed2b"


class ImmediacyError(RuntimeError):
    """Fail-closed trough-immediacy association error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _import_attribution(spec: dict[str, Any]) -> Any:
    path = _resolve(spec["inputs"]["accepted_attribution_runner"]["path"])
    module_spec = importlib.util.spec_from_file_location(
        "accepted_formdepth_attribution_immed", path
    )
    if module_spec is None or module_spec.loader is None:
        raise ImmediacyError("cannot load accepted attribution helpers")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ImmediacyError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_TROUGH_IMMEDIACY_ESTIMATES"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_CROSSER_TROUGH_OFFSET_COUNTS_ONLY"
    ):
        raise ImmediacyError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ImmediacyError(f"input identity mismatch: {name}")
    path_data = json.loads(
        _resolve(spec["inputs"]["path_data_result"]["path"]).read_text()
    )
    path_result = json.loads(
        _resolve(spec["inputs"]["path_result"]["path"]).read_text()
    )
    attribution = json.loads(
        _resolve(spec["inputs"]["attribution_result"]["path"]).read_text()
    )
    activation = spec["activation"]
    if path_data["status"] != activation["required_path_data_status"]:
        raise ImmediacyError("path data domain is not activated")
    if path_result["classification"] != activation["required_path_classification"]:
        raise ImmediacyError("path timing result is not activated")
    if attribution["classification"] != activation["required_attribution_classification"]:
        raise ImmediacyError("formation-depth attribution is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise ImmediacyError("prohibited boundary changed")
    return spec


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    source = pd.read_csv(
        _resolve(spec["inputs"]["path_panel"]["path"]), parse_dates=["trade_date"]
    )
    activation = spec["activation"]
    if len(source) != activation["expected_path_panel_rows"]:
        raise ImmediacyError("path panel row count changed")
    if int(source["path_topology_complete"].sum()) != activation[
        "expected_path_topology_complete_rows"
    ]:
        raise ImmediacyError("path-topology-complete row count changed")
    source = source[source["path_topology_complete"]].copy()
    count_pairs = {
        "crossing_first_trough_share_h3": (
            "crossing_trough_h3_offset1_count",
            "crossing_response_count",
        ),
        "crossing_first_trough_share_h5": (
            "crossing_trough_h5_offset1_count",
            "crossing_response_count",
        ),
        "accepted_first_trough_share_h3": (
            "accepted_trough_h3_offset1_count",
            "accepted_response_count",
        ),
        "rejected_first_trough_share_h3": (
            "rejected_trough_h3_offset1_count",
            "rejected_response_count",
        ),
    }
    for target, (numerator, denominator) in count_pairs.items():
        if (source[denominator] <= 0).any():
            raise ImmediacyError(f"nonpositive response denominator: {denominator}")
        if (source[numerator] > source[denominator]).any():
            raise ImmediacyError(f"first-trough count exceeds response count: {target}")
        source[target] = source[numerator] / source[denominator]
    attribution = pd.read_csv(
        _resolve(spec["inputs"]["attribution_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    state = spec["state"]["pit"]
    controls = spec["controls"]
    attr_columns = [
        *keys,
        "available_at",
        "event_year",
        "session_ordinal",
        state,
        *controls,
    ]
    panel = source[[*keys, *count_pairs]].merge(
        attribution[attr_columns], on=keys, how="left", validate="one_to_one"
    )
    panel = panel.dropna(subset=[state, *controls]).copy()
    if len(panel) != activation["expected_complete_five_control_rows"]:
        raise ImmediacyError("complete five-control row count changed")
    cell_counts = panel.groupby(keys[1:], sort=True).size()
    if len(cell_counts) != activation["expected_groups"]:
        raise ImmediacyError("cell count changed")
    if cell_counts.min() < activation["minimum_complete_five_control_rows_per_cell"]:
        raise ImmediacyError("per-cell support below frozen floor")
    response_columns = list(count_pairs)
    values = panel[response_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or (values > 1).any():
        raise ImmediacyError("invalid first-trough response share")
    if panel["event_year"].max() > 2023:
        raise ImmediacyError("post-2023 row reached immediacy analysis")
    support = {
        "path_topology_complete_rows": len(source),
        "complete_five_control_rows": len(panel),
        "groups": len(cell_counts),
        "minimum_complete_rows_per_cell": int(cell_counts.min()),
        "years": sorted(int(value) for value in panel["event_year"].unique()),
        "joint_available_at": activation["joint_available_at"],
        "response_begins": activation["response_begins"],
    }
    columns = [
        *keys,
        "available_at",
        "event_year",
        "session_ordinal",
        state,
        *controls,
        *response_columns,
    ]
    return panel[columns].sort_values(keys).reset_index(drop=True), support


def _append_partial(
    rows: list[dict[str, Any]],
    group: pd.DataFrame,
    spec: dict[str, Any],
    helper: Any,
    response: str,
    horizon: int,
    scope: str,
    scope_value: str,
    view: str,
    denominator: str,
    closing_arm: str = "",
) -> None:
    n, rho = helper._partial_rank(
        group, spec["state"]["pit"], response, spec["controls"]
    )
    rows.append(
        {
            "audit_type": "partial_rank",
            "scope": scope,
            "scope_value": scope_value,
            "market_view": view,
            "denominator": denominator,
            "horizon": horizon,
            "closing_arm": closing_arm,
            "n": n,
            "partial_rho": rho,
            "low_n": np.nan,
            "high_n": np.nan,
            "tail_residual_gap": np.nan,
        }
    )


def _audit(panel: pd.DataFrame, spec: dict[str, Any], helper: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    primary = "crossing_first_trough_share_h3"
    neighbor = "crossing_first_trough_share_h5"
    for (view, denominator), group in panel.groupby(
        ["market_view", "denominator"], sort=True
    ):
        group = group.sort_values("trade_date")
        _append_partial(
            rows, group, spec, helper, primary, 3, "cell", f"{view}:{denominator}",
            view, denominator,
        )
        _append_partial(
            rows, group, spec, helper, neighbor, 5, "cell", f"{view}:{denominator}",
            view, denominator,
        )
        for block, years in spec["scopes"]["blocks"].items():
            _append_partial(
                rows, group[group["event_year"].isin(years)], spec, helper, primary,
                3, "block", block, view, denominator,
            )
        for year in spec["scopes"]["pit_supported_years"]:
            _append_partial(
                rows, group[group["event_year"] == year], spec, helper, primary, 3,
                "year", str(year), view, denominator,
            )
            keep_years = [
                value for value in spec["scopes"]["pit_supported_years"] if value != year
            ]
            _append_partial(
                rows, group[group["event_year"].isin(keep_years)], spec, helper, primary,
                3, "leave_one_year_out", str(year), view, denominator,
            )
        for horizon, response in ((3, primary), (5, neighbor)):
            for phase in range(horizon):
                _append_partial(
                    rows, group[group["session_ordinal"] % horizon == phase], spec,
                    helper, response, horizon, "phase", str(phase), view, denominator,
                )
        for arm in ("accepted", "rejected"):
            _append_partial(
                rows, group, spec, helper, f"{arm}_first_trough_share_h3", 3,
                "arm_robustness", arm, view, denominator, closing_arm=arm,
            )
        n, low_n, high_n, gap = helper._tail_residual_gap(
            group,
            spec["state"]["pit"],
            primary,
            spec["controls"],
            spec["state"]["pit_low_maximum"],
            spec["state"]["pit_high_minimum"],
        )
        rows.append(
            {
                "audit_type": "tail_residual_gap",
                "scope": "cell",
                "scope_value": f"{view}:{denominator}",
                "market_view": view,
                "denominator": denominator,
                "horizon": 3,
                "closing_arm": "",
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
            "horizon",
            "closing_arm",
        ]
    ).reset_index(drop=True)


def _median(values: pd.Series | list[float]) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _evaluate(audit: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    partial = audit[audit["audit_type"] == "partial_rank"]
    primary_rows = partial[(partial["scope"] == "cell") & (partial["horizon"] == 3)]
    primary_rho = _median(primary_rows["partial_rho"])
    direction = _sign(primary_rho)
    neighbor_rho = _median(
        partial[(partial["scope"] == "cell") & (partial["horizon"] == 5)][
            "partial_rho"
        ]
    )
    block_medians = {
        block: _median(
            partial[(partial["scope"] == "block") & (partial["scope_value"] == block)][
                "partial_rho"
            ]
        )
        for block in spec["scopes"]["blocks"]
    }
    year_medians = {
        str(year): _median(
            partial[
                (partial["scope"] == "year")
                & (partial["scope_value"] == str(year))
            ]["partial_rho"]
        )
        for year in spec["scopes"]["pit_supported_years"]
    }
    loo_medians = {
        str(year): _median(
            partial[
                (partial["scope"] == "leave_one_year_out")
                & (partial["scope_value"] == str(year))
            ]["partial_rho"]
        )
        for year in spec["scopes"]["pit_supported_years"]
    }
    phase_signs = {
        str(horizon): [
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
        for horizon in (3, 5)
    }
    arm_medians = {
        arm: _median(
            partial[
                (partial["scope"] == "arm_robustness")
                & (partial["closing_arm"] == arm)
            ]["partial_rho"]
        )
        for arm in ("accepted", "rejected")
    }
    tail_gap = _median(
        audit[audit["audit_type"] == "tail_residual_gap"]["tail_residual_gap"]
    )
    gate = spec["two_sided_gates"]
    checks = {
        "primary": abs(primary_rho) >= gate["minimum_absolute_median_h3_partial_rho"],
        "cells": int((_sign_series(primary_rows["partial_rho"]) == direction).sum())
        >= gate["minimum_same_direction_cells"],
        "blocks": direction != 0
        and all(
            _sign(value) == direction
            and abs(value) >= gate["minimum_absolute_each_block_partial_rho"]
            for value in block_medians.values()
        ),
        "years": direction != 0
        and all(_sign(value) == direction for value in year_medians.values()),
        "leave_one_year_out": direction != 0
        and all(_sign(value) == direction for value in loo_medians.values()),
        "neighbor": _sign(neighbor_rho) == direction
        and abs(neighbor_rho) >= gate["minimum_absolute_h5_partial_rho"],
        "h3_phases": sum(value == direction for value in phase_signs["3"])
        >= gate["minimum_same_direction_h3_phases"],
        "h5_phases": sum(value == direction for value in phase_signs["5"])
        >= gate["minimum_same_direction_h5_phases"],
        "tail_gap": _sign(tail_gap) == direction
        and abs(tail_gap) >= gate["minimum_absolute_tail_residual_gap"],
        "closing_arms": direction != 0
        and all(_sign(value) == direction for value in arm_medians.values()),
    }
    passed = all(checks.values())
    if passed and direction > 0:
        classification = "EARLIER_TROUGH_WITH_FORMATION_DEPTH"
    elif passed and direction < 0:
        classification = "LATER_TROUGH_WITH_FORMATION_DEPTH"
    else:
        classification = "NO_STABLE_TROUGH_IMMEDIACY_SHIFT"
    evaluation = {
        "direction": direction,
        "median_h3_partial_rho": primary_rho,
        "same_direction_cells": int(
            (_sign_series(primary_rows["partial_rho"]) == direction).sum()
        ),
        "h5_median_partial_rho": neighbor_rho,
        "block_median_partial_rho": block_medians,
        "year_median_partial_rho": year_medians,
        "leave_one_year_out_median_partial_rho": loo_medians,
        "phase_signs": phase_signs,
        "closing_arm_h3_median_partial_rho": arm_medians,
        "median_tail_residual_gap": tail_gap,
        "checks": checks,
        "pass": passed,
    }
    return evaluation, classification


def _sign_series(values: pd.Series) -> pd.Series:
    return values.map(_sign)


def _write_report(result: dict[str, Any]) -> None:
    item = result["evaluation"]
    lines = [
        "# MKT-FORMDEPTH-IMMED-001 trough immediacy",
        "",
        "## Decision",
        "",
        f"`{result['classification']}`",
        "",
        "The future trough share is response attribution only. It is unavailable",
        "at the 15:30 predictor clock and is not an executable timing signal.",
        "",
        "## Fixed result",
        "",
        f"- h=3 median PIT partial rho: {item['median_h3_partial_rho']:.6f}",
        f"- same-direction cells: {item['same_direction_cells']}/8",
        f"- h=5 median PIT partial rho: {item['h5_median_partial_rho']:.6f}",
        f"- block medians: {item['block_median_partial_rho']}",
        f"- supported-year medians: {item['year_median_partial_rho']}",
        f"- closing-arm medians: {item['closing_arm_h3_median_partial_rho']}",
        f"- controlled tail share gap: {item['median_tail_residual_gap']:.6f}",
        f"- checks: {item['checks']}",
        "",
        "No strategy fields, post-2023 data, or CY-011 were read.",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    helper = _import_attribution(spec)
    helper._resource_guard(spec, started)
    panel, support = _load_panel(spec)
    audit = _audit(panel, spec, helper)
    evaluation, classification = _evaluate(audit, spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_TROUGH_IMMEDIACY_ASSOCIATION",
        "classification": classification,
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "joint_information_clock": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
        "support": support,
        "evaluation": evaluation,
        "future_trough_used_as_predictor": False,
        "habitat_action": "NONE",
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "resource_contract": spec["resource_budget"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "panel_sha256": sha256_file(PANEL_PATH),
            "response_audit_sha256": sha256_file(AUDIT_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(helper._clean(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report(result)
    helper._resource_guard(spec, started)
    durable = sum(
        path.stat().st_size for path in (PANEL_PATH, AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise ImmediacyError("durable output ceiling breached")
    print(json.dumps(helper._clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
