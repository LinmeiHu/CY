#!/usr/bin/env python3
"""Estimate the frozen formation-depth adverse-path timing decomposition."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-PATH-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-001_panel.csv"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-001_response_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-PATH-001_timing.md"
EXPECTED_SPEC_SHA256 = "740b38a0be82258329c7c722ae78433e80833b1b7189b98ed3d9b1efc6bbbfd6"


class PathTimingError(RuntimeError):
    """Fail-closed adverse-path timing analysis error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _import(path: Path, name: str) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise PathTimingError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise PathTimingError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_ADVERSE_PATH_TIMING_ESTIMATES"
        or spec["outcome_access"] != "EXISTING_PRE2024_CROSSER_PATH_COMPONENTS_ONLY"
    ):
        raise PathTimingError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise PathTimingError(f"input identity mismatch: {name}")
    path_result = json.loads(
        _resolve(spec["inputs"]["path_result"]["path"]).read_text()
    )
    attribution = json.loads(
        _resolve(spec["inputs"]["attribution_result"]["path"]).read_text()
    )
    closing = json.loads(
        _resolve(spec["inputs"]["closing_topology_result"]["path"]).read_text()
    )
    activation = spec["activation"]
    if path_result["status"] != activation["required_path_status"]:
        raise PathTimingError("path component domain is not activated")
    if attribution["classification"] != activation["required_attribution_classification"]:
        raise PathTimingError("formation-depth attribution is not activated")
    if closing["classification"] != activation["required_closing_classification"]:
        raise PathTimingError("closing-state topology is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise PathTimingError("prohibited boundary changed")
    return spec


def _response_columns() -> list[str]:
    components = (
        "preopen_path_to_trough",
        "trough_session_intraday",
        "post_trough_recovery",
    )
    return [
        f"{arm}_{component}_h{horizon}_mean"
        for arm in ("crossing", "accepted", "rejected")
        for component in components
        for horizon in (1, 3, 5)
    ]


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    path_panel = pd.read_csv(
        _resolve(spec["inputs"]["path_panel"]["path"]), parse_dates=["trade_date"]
    )
    activation = spec["activation"]
    if len(path_panel) != activation["expected_path_panel_rows"]:
        raise PathTimingError("path panel row count changed")
    if int(path_panel["path_topology_complete"].sum()) != activation[
        "expected_path_topology_complete_rows"
    ]:
        raise PathTimingError("path-topology-complete row count changed")
    terminal = [
        f"crossing_terminal_log_return_h{horizon}_mean" for horizon in (1, 3, 5)
    ]
    path_panel = path_panel.loc[
        path_panel["path_topology_complete"], [*keys, *_response_columns(), *terminal]
    ].copy()
    attribution = pd.read_csv(
        _resolve(spec["inputs"]["attribution_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    state = spec["state"]
    controls = spec["controls"]
    attr_columns = [
        *keys,
        "available_at",
        "event_year",
        "session_ordinal",
        state["absolute"],
        state["pit"],
        *controls,
    ]
    panel = path_panel.merge(
        attribution[attr_columns], on=keys, how="left", validate="one_to_one"
    )
    panel = panel.dropna(subset=[state["pit"], *controls]).copy()
    if len(panel) != activation["expected_complete_five_control_rows"]:
        raise PathTimingError("complete five-control row count changed")
    cell_counts = panel.groupby(keys[1:], sort=True).size()
    if len(cell_counts) != activation["expected_groups"]:
        raise PathTimingError("cell count changed")
    if cell_counts.min() < activation["minimum_complete_five_control_rows_per_cell"]:
        raise PathTimingError("per-cell complete support below frozen floor")
    if len(panel) < activation["minimum_complete_five_control_rows"]:
        raise PathTimingError("complete support below frozen floor")
    if panel["event_year"].max() > 2023:
        raise PathTimingError("post-2023 row reached timing analysis")
    support = {
        "path_topology_complete_rows": len(path_panel),
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
        state["absolute"],
        state["pit"],
        *controls,
        *_response_columns(),
        *terminal,
    ]
    return panel[columns].sort_values(keys).reset_index(drop=True), support


def _adapt_panel(panel: pd.DataFrame) -> pd.DataFrame:
    adapted = panel.copy()
    for horizon in (1, 3, 5):
        adapted[f"crossing_adverse_log_excursion_h{horizon}_mean"] = adapted[
            f"crossing_preopen_path_to_trough_h{horizon}_mean"
        ]
        adapted[f"noncrossing_adverse_log_excursion_h{horizon}_mean"] = adapted[
            f"crossing_trough_session_intraday_h{horizon}_mean"
        ]
        adapted[f"paired_adverse_h{horizon}"] = adapted[
            f"crossing_post_trough_recovery_h{horizon}_mean"
        ]
        terminal = adapted[f"crossing_terminal_log_return_h{horizon}_mean"]
        adapted[f"noncrossing_terminal_log_return_h{horizon}_mean"] = terminal
    return adapted


def _adapt_spec(spec: dict[str, Any]) -> dict[str, Any]:
    adapted = dict(spec)
    adapted["channels"] = {
        "CROSSER_DOWNSIDE": "pre-open path to trough",
        "NONCROSSER_DOWNSIDE": "trough-session intraday",
        "CROSSER_MINUS_NONCROSSER": "post-trough recovery diagnostic",
    }
    return adapted


def _append_arm_robustness(
    audit: pd.DataFrame,
    panel: pd.DataFrame,
    spec: dict[str, Any],
    attribution: Any,
) -> pd.DataFrame:
    state = spec["state"]
    controls = spec["controls"]
    rows: list[dict[str, Any]] = []
    definitions = {
        "CROSSER_DOWNSIDE": "preopen_path_to_trough",
        "NONCROSSER_DOWNSIDE": "trough_session_intraday",
    }
    for (view, denominator), group in panel.groupby(
        ["market_view", "denominator"], sort=True
    ):
        for channel, component in definitions.items():
            for arm in spec["closing_arm_robustness"]["arms"]:
                response = f"{arm}_{component}_h3_mean"
                n, rho = attribution._partial_rank(
                    group, state["pit"], response, controls
                )
                rows.append(
                    {
                        "audit_type": "arm_robustness",
                        "channel": channel,
                        "scope": "cell",
                        "scope_value": f"{view}:{denominator}:{arm}",
                        "market_view": view,
                        "denominator": denominator,
                        "coordinate": "pit",
                        "horizon": 3,
                        "n": n,
                        "partial_rho": rho,
                        "low_n": np.nan,
                        "high_n": np.nan,
                        "tail_residual_gap": np.nan,
                        "closing_arm": arm,
                    }
                )
    base = audit.copy()
    base["closing_arm"] = ""
    return pd.concat([base, pd.DataFrame(rows)], ignore_index=True).sort_values(
        [
            "audit_type",
            "channel",
            "scope",
            "scope_value",
            "market_view",
            "denominator",
            "coordinate",
            "horizon",
            "closing_arm",
        ]
    ).reset_index(drop=True)


def _evaluate(
    audit: pd.DataFrame, spec: dict[str, Any], topology: Any
) -> tuple[dict[str, Any], str]:
    old_channels = (
        "CROSSER_DOWNSIDE",
        "NONCROSSER_DOWNSIDE",
        "CROSSER_MINUS_NONCROSSER",
    )
    summaries = {
        channel: topology._channel_summary(audit, channel, spec)
        for channel in old_channels
    }
    gate = spec["component_gates"]
    for channel in old_channels[:2]:
        item = summaries[channel]
        arm_rows = audit[
            (audit["audit_type"] == "arm_robustness") & (audit["channel"] == channel)
        ]
        arm_medians = {
            arm: topology._median(
                arm_rows[arm_rows["closing_arm"] == arm]["partial_rho"]
            )
            for arm in spec["closing_arm_robustness"]["arms"]
        }
        checks = {
            "primary": item["median_h3_partial_rho"]
            <= gate["maximum_median_h3_partial_rho"],
            "cells": item["negative_cells"] >= gate["minimum_negative_cells"],
            "blocks": all(
                value <= gate["maximum_each_block_partial_rho"]
                for value in item["block_median_partial_rho"].values()
            ),
            "years": all(value < 0 for value in item["year_median_partial_rho"].values()),
            "leave_one_year_out": all(
                value < 0 for value in item["leave_one_year_out_median_partial_rho"].values()
            ),
            "neighbors": all(
                value < 0 for value in item["neighbor_median_partial_rho"].values()
            ),
            "h3_phases": sum(value < 0 for value in item["phase_signs"]["3"])
            >= gate["minimum_negative_h3_phases"],
            "h5_phases": sum(value < 0 for value in item["phase_signs"]["5"])
            >= gate["minimum_negative_h5_phases"],
            "tail_gap": item["median_tail_residual_gap"]
            <= gate["maximum_median_tail_residual_gap"],
            "closing_arms": all(value < 0 for value in arm_medians.values()),
        }
        item["closing_arm_h3_median_partial_rho"] = arm_medians
        item["checks"] = checks
        item["pass"] = all(checks.values())
    summaries["CROSSER_MINUS_NONCROSSER"]["pass"] = None
    summaries["CROSSER_MINUS_NONCROSSER"]["checks"] = {
        "diagnostic_only": True
    }
    preopen_pass = summaries["CROSSER_DOWNSIDE"]["pass"]
    intraday_pass = summaries["NONCROSSER_DOWNSIDE"]["pass"]
    if preopen_pass and intraday_pass:
        classification = "MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH"
    elif preopen_pass:
        classification = "PREOPEN_PATH_LOCALIZED_DOWNSIDE"
    elif intraday_pass:
        classification = "TROUGH_SESSION_INTRADAY_LOCALIZED_DOWNSIDE"
    else:
        classification = "ADVERSE_PATH_TIMING_NOT_RESOLVED"
    terminal = audit[
        (audit["audit_type"] == "terminal_diagnostic")
        & (audit["channel"] == "CROSSER_DOWNSIDE")
    ]
    terminal_diagnostics = {
        str(horizon): topology._median(
            terminal[terminal["horizon"] == horizon]["partial_rho"]
        )
        for horizon in (1, 3, 5)
    }
    channel_map = {
        "CROSSER_DOWNSIDE": "PREOPEN_PATH_DOWNSIDE",
        "NONCROSSER_DOWNSIDE": "TROUGH_SESSION_INTRADAY_DOWNSIDE",
        "CROSSER_MINUS_NONCROSSER": "POST_TROUGH_RECOVERY_DIAGNOSTIC",
    }
    canonical = {channel_map[name]: item for name, item in summaries.items()}
    return {"channels": canonical, "terminal_diagnostics": terminal_diagnostics}, classification


def _canonical_audit(audit: pd.DataFrame) -> pd.DataFrame:
    channel_map = {
        "CROSSER_DOWNSIDE": "PREOPEN_PATH_DOWNSIDE",
        "NONCROSSER_DOWNSIDE": "TROUGH_SESSION_INTRADAY_DOWNSIDE",
        "CROSSER_MINUS_NONCROSSER": "POST_TROUGH_RECOVERY_DIAGNOSTIC",
    }
    result = audit.copy()
    result["channel"] = result["channel"].map(channel_map)
    return result


def _write_report(result: dict[str, Any]) -> None:
    channels = result["evaluation"]["channels"]
    lines = [
        "# MKT-FORMDEPTH-PATH-001 adverse-path timing",
        "",
        "## Decision",
        "",
        f"`{result['classification']}`",
        "",
        "This is daily-bar response attribution only. Future opens, lows, trough",
        "sessions, and recovery fields are not predictors or executable signals.",
        "",
        "## Fixed support",
        "",
        f"- complete five-control rows: {result['support']['complete_five_control_rows']:,}",
        f"- minimum rows per cell: {result['support']['minimum_complete_rows_per_cell']:,}",
        f"- joint information clock: {result['joint_information_clock']}",
        "",
        "## Classifying channels",
        "",
    ]
    for channel in (
        "PREOPEN_PATH_DOWNSIDE",
        "TROUGH_SESSION_INTRADAY_DOWNSIDE",
    ):
        item = channels[channel]
        lines.extend(
            [
                f"### {channel}",
                "",
                f"- gate: **{'PASS' if item['pass'] else 'FAIL'}**",
                f"- h=3 median PIT partial rho: {item['median_h3_partial_rho']:.6f}",
                f"- negative cells: {item['negative_cells']}/8",
                f"- h=1/h=5 medians: {item['neighbor_median_partial_rho']}",
                f"- block medians: {item['block_median_partial_rho']}",
                f"- supported-year medians: {item['year_median_partial_rho']}",
                f"- closing-arm h=3 medians: {item['closing_arm_h3_median_partial_rho']}",
                (
                    "- median controlled PIT-tail residual gap: "
                    f"{item['median_tail_residual_gap']:.6f}"
                ),
                f"- checks: {item['checks']}",
                "",
            ]
        )
    recovery = channels["POST_TROUGH_RECOVERY_DIAGNOSTIC"]
    lines.extend(
        [
            "## Diagnostics",
            "",
            f"- recovery h=3 median partial rho: {recovery['median_h3_partial_rho']:.6f}",
            f"- recovery h=1/h=5: {recovery['neighbor_median_partial_rho']}",
            f"- terminal: {result['evaluation']['terminal_diagnostics']}",
            "",
            "Recovery and terminal response cannot promote or rescue a timing",
            "classification. No strategy fields, post-2023 data, or CY-011 were read.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    topology = _import(
        _resolve(spec["inputs"]["accepted_topology_runner"]["path"]),
        "accepted_topology_path",
    )
    attribution = _import(
        _resolve(spec["inputs"]["accepted_attribution_runner"]["path"]),
        "accepted_attribution_path",
    )
    topology._guard(spec, started)
    panel, support = _load_panel(spec)
    adapted_spec = _adapt_spec(spec)
    audit = topology._audit(_adapt_panel(panel), adapted_spec, attribution)
    audit = _append_arm_robustness(audit, panel, spec, attribution)
    evaluation, classification = _evaluate(audit, adapted_spec, topology)
    audit = _canonical_audit(audit)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_ADVERSE_PATH_TIMING_ASSOCIATION",
        "classification": classification,
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "joint_information_clock": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
        "support": support,
        "evaluation": evaluation,
        "recovery_can_promote": False,
        "terminal_can_promote": False,
        "future_components_used_as_predictors": False,
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
        json.dumps(topology._clean(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report(result)
    topology._guard(spec, started)
    durable = sum(
        path.stat().st_size for path in (PANEL_PATH, AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise PathTimingError("durable output ceiling breached")
    print(json.dumps(topology._clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
