#!/usr/bin/env python3
"""Estimate the frozen formation-depth crossing/noncrossing response topology."""

from __future__ import annotations

import hashlib
import importlib.util
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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-PROP-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-001_panel.csv"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-001_response_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-PROP-001_topology.md"
EXPECTED_SPEC_SHA256 = "26f9cdcb8c8fdaeb00f102e4f8c31d9174d0ca2180da0de8955eff4e81b1c27e"


class PropagationError(RuntimeError):
    """Fail-closed membership-response topology error."""


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
        "accepted_formdepth_attribution", path
    )
    if module_spec is None or module_spec.loader is None:
        raise PropagationError("cannot load accepted attribution helpers")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


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
        raise PropagationError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_MEMBERSHIP_RESOLVED_RESPONSE_ESTIMATES"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_MEMBERSHIP_RESOLVED_H1_H3_H5_RESPONSE_ONLY"
    ):
        raise PropagationError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise PropagationError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise PropagationError("prohibited boundary changed")
    topology = json.loads(
        _resolve(spec["inputs"]["topology_result"]["path"]).read_text()
    )
    if topology["status"] != spec["activation"]["required_topology_status"]:
        raise PropagationError("membership response domain is not activated")
    attribution = json.loads(
        _resolve(spec["inputs"]["attribution_result"]["path"]).read_text()
    )
    if (
        attribution["classification"]
        != spec["activation"]["required_attribution_classification"]
    ):
        raise PropagationError("accepted formation-depth attribution is not activated")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise PropagationError("system memory headroom below frozen floor")
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise PropagationError("process peak RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise PropagationError("wall-clock ceiling breached")


def _median(values: pd.Series | np.ndarray | list[float]) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    topology = pd.read_csv(
        _resolve(spec["inputs"]["topology_panel"]["path"]), parse_dates=["trade_date"]
    )
    if len(topology) != spec["activation"]["expected_topology_rows"]:
        raise PropagationError("topology panel row count changed")
    if int(topology["topology_complete"].sum()) != spec["activation"][
        "expected_topology_complete_rows"
    ]:
        raise PropagationError("topology-complete row count changed")
    topology = topology[topology["topology_complete"]].copy()
    # State/control coordinates are authoritative in the accepted attribution
    # panel. The topology panel's copies have passed through one extra CSV
    # serialization and are not used as analysis inputs.
    state = spec["state"]
    topology = topology.drop(columns=[state["absolute"], state["pit"]])
    attribution = pd.read_csv(
        _resolve(spec["inputs"]["attribution_panel"]["path"]), parse_dates=["trade_date"]
    )
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
    panel = topology.merge(
        attribution[attr_columns],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_attr"),
    )
    required = [state["pit"], *controls]
    panel = panel.dropna(subset=required).copy()
    if len(panel) != spec["activation"]["expected_complete_five_control_rows"]:
        raise PropagationError("complete five-control row count changed")
    cell_counts = panel.groupby(keys[1:], sort=True).size()
    if len(cell_counts) != spec["activation"]["expected_groups"]:
        raise PropagationError("cell count changed")
    if cell_counts.min() < spec["activation"]["minimum_complete_five_control_rows_per_cell"]:
        raise PropagationError("per-cell complete support below frozen floor")
    if len(panel) < spec["activation"]["minimum_complete_five_control_rows"]:
        raise PropagationError("complete support below frozen floor")
    for horizon in (1, 3, 5):
        crossing_adverse = f"crossing_adverse_log_excursion_h{horizon}_mean"
        noncrossing_adverse = f"noncrossing_adverse_log_excursion_h{horizon}_mean"
        crossing_terminal = f"crossing_terminal_log_return_h{horizon}_mean"
        noncrossing_terminal = f"noncrossing_terminal_log_return_h{horizon}_mean"
        panel[f"paired_adverse_h{horizon}"] = (
            panel[crossing_adverse] - panel[noncrossing_adverse]
        )
        panel[f"paired_terminal_h{horizon}"] = (
            panel[crossing_terminal] - panel[noncrossing_terminal]
        )
    if panel["event_year"].max() > 2023:
        raise PropagationError("post-2023 row reached topology analysis")
    support = {
        "topology_complete_rows": len(topology),
        "complete_five_control_rows": len(panel),
        "groups": len(cell_counts),
        "minimum_complete_rows_per_cell": int(cell_counts.min()),
        "years": sorted(int(value) for value in panel["event_year"].unique()),
        "joint_available_at": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
    }
    response_columns = [
        column
        for column in panel
        if (
            column.startswith("crossing_adverse_")
            or column.startswith("noncrossing_adverse_")
            or column.startswith("crossing_terminal_")
            or column.startswith("noncrossing_terminal_")
            or column.startswith("paired_adverse_")
            or column.startswith("paired_terminal_")
        )
        and column.endswith(("_mean", "h1", "h3", "h5"))
    ]
    columns = [
        *keys,
        "available_at",
        "event_year",
        "session_ordinal",
        state["absolute"],
        state["pit"],
        *controls,
        *response_columns,
    ]
    return panel[columns].sort_values(keys).reset_index(drop=True), support


def _response_field(channel: str, horizon: int, terminal: bool = False) -> str:
    kind = "terminal_log_return" if terminal else "adverse_log_excursion"
    if channel == "CROSSER_DOWNSIDE":
        return f"crossing_{kind}_h{horizon}_mean"
    if channel == "NONCROSSER_DOWNSIDE":
        return f"noncrossing_{kind}_h{horizon}_mean"
    prefix = "paired_terminal" if terminal else "paired_adverse"
    return f"{prefix}_h{horizon}"


def _audit(panel: pd.DataFrame, spec: dict[str, Any], helper: Any) -> pd.DataFrame:
    state = spec["state"]
    controls = spec["controls"]
    rows: list[dict[str, Any]] = []

    def append_partial(
        group: pd.DataFrame,
        channel: str,
        coordinate: str,
        target: str,
        horizon: int,
        scope: str,
        scope_value: str,
        view: str,
        denominator: str,
        terminal: bool = False,
    ) -> None:
        response = _response_field(channel, horizon, terminal)
        n, rho = helper._partial_rank(group, target, response, controls)
        rows.append(
            {
                "audit_type": "terminal_diagnostic" if terminal else "partial_rank",
                "channel": channel,
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
        for channel in spec["channels"]:
            for coordinate, target in (
                ("absolute", state["absolute"]),
                ("pit", state["pit"]),
            ):
                for horizon in (1, 3, 5):
                    append_partial(
                        group,
                        channel,
                        coordinate,
                        target,
                        horizon,
                        "cell",
                        f"{view}:{denominator}",
                        view,
                        denominator,
                    )
            for block, years in spec["scopes"]["blocks"].items():
                append_partial(
                    group[group["event_year"].isin(years)],
                    channel,
                    "pit",
                    state["pit"],
                    3,
                    "block",
                    block,
                    view,
                    denominator,
                )
            for year in spec["scopes"]["pit_supported_years"]:
                append_partial(
                    group[group["event_year"] == year],
                    channel,
                    "pit",
                    state["pit"],
                    3,
                    "year",
                    str(year),
                    view,
                    denominator,
                )
                keep_years = [
                    value
                    for value in spec["scopes"]["pit_supported_years"]
                    if value != year
                ]
                append_partial(
                    group[group["event_year"].isin(keep_years)],
                    channel,
                    "pit",
                    state["pit"],
                    3,
                    "leave_one_year_out",
                    str(year),
                    view,
                    denominator,
                )
            for horizon in (3, 5):
                for phase in range(horizon):
                    append_partial(
                        group[group["session_ordinal"] % horizon == phase],
                        channel,
                        "pit",
                        state["pit"],
                        horizon,
                        "phase",
                        str(phase),
                        view,
                        denominator,
                    )
            response = _response_field(channel, 3)
            n, low_n, high_n, gap = helper._tail_residual_gap(
                group,
                state["pit"],
                response,
                controls,
                state["pit_low_maximum"],
                state["pit_high_minimum"],
            )
            rows.append(
                {
                    "audit_type": "tail_residual_gap",
                    "channel": channel,
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
        for channel in ("CROSSER_DOWNSIDE", "NONCROSSER_DOWNSIDE"):
            for horizon in (1, 3, 5):
                append_partial(
                    group,
                    channel,
                    "pit",
                    state["pit"],
                    horizon,
                    "cell",
                    f"{view}:{denominator}",
                    view,
                    denominator,
                    terminal=True,
                )
    return pd.DataFrame(rows).sort_values(
        [
            "audit_type",
            "channel",
            "scope",
            "scope_value",
            "market_view",
            "denominator",
            "coordinate",
            "horizon",
        ]
    ).reset_index(drop=True)


def _channel_summary(audit: pd.DataFrame, channel: str, spec: dict[str, Any]) -> dict[str, Any]:
    partial = audit[
        (audit["audit_type"] == "partial_rank") & (audit["channel"] == channel)
    ]
    primary = partial[
        (partial["scope"] == "cell")
        & (partial["coordinate"] == "pit")
        & (partial["horizon"] == 3)
    ]
    median_h3 = _median(primary["partial_rho"])
    negative_cells = int((primary["partial_rho"] < 0).sum())
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
                (partial["scope"] == "block") & (partial["scope_value"] == block)
            ]["partial_rho"]
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
    tail_gap = _median(
        audit[
            (audit["audit_type"] == "tail_residual_gap")
            & (audit["channel"] == channel)
        ]["tail_residual_gap"]
    )
    return {
        "median_h3_partial_rho": median_h3,
        "negative_cells": negative_cells,
        "neighbor_median_partial_rho": neighbor_medians,
        "block_median_partial_rho": block_medians,
        "year_median_partial_rho": year_medians,
        "leave_one_year_out_median_partial_rho": loo_medians,
        "phase_signs": phase_signs,
        "median_tail_residual_gap": tail_gap,
    }


def _evaluate(audit: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    summaries = {
        channel: _channel_summary(audit, channel, spec) for channel in spec["channels"]
    }
    arm_gate = spec["arm_channel_gates"]
    for channel in ("CROSSER_DOWNSIDE", "NONCROSSER_DOWNSIDE"):
        item = summaries[channel]
        checks = {
            "primary": item["median_h3_partial_rho"]
            <= arm_gate["maximum_median_h3_partial_rho"],
            "cells": item["negative_cells"] >= arm_gate["minimum_negative_cells"],
            "blocks": all(
                value <= arm_gate["maximum_each_block_partial_rho"]
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
            >= arm_gate["minimum_negative_h3_phases"],
            "h5_phases": sum(value < 0 for value in item["phase_signs"]["5"])
            >= arm_gate["minimum_negative_h5_phases"],
            "tail_gap": item["median_tail_residual_gap"]
            <= arm_gate["maximum_median_tail_residual_gap"],
        }
        item["checks"] = checks
        item["pass"] = all(checks.values())
    paired = summaries["CROSSER_MINUS_NONCROSSER"]
    paired_gate = spec["paired_localization_gates"]
    paired_checks = {
        "primary": paired["median_h3_partial_rho"]
        <= paired_gate["maximum_median_h3_partial_rho"],
        "cells": paired["negative_cells"] >= paired_gate["minimum_negative_cells"],
        "blocks": all(value < 0 for value in paired["block_median_partial_rho"].values()),
        "neighbors": all(
            value <= 0 for value in paired["neighbor_median_partial_rho"].values()
        ),
        "tail_gap": paired["median_tail_residual_gap"]
        <= paired_gate["maximum_median_tail_residual_gap"],
    }
    paired["checks"] = paired_checks
    paired["pass"] = all(paired_checks.values())
    crossing_pass = summaries["CROSSER_DOWNSIDE"]["pass"]
    noncrossing_pass = summaries["NONCROSSER_DOWNSIDE"]["pass"]
    paired_pass = summaries["CROSSER_MINUS_NONCROSSER"]["pass"]
    if crossing_pass and noncrossing_pass:
        classification = "CROSSER_AND_NONCROSSER_DOWNSIDE_PROPAGATION"
    elif crossing_pass and paired_pass:
        classification = "LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY"
    elif noncrossing_pass and not crossing_pass:
        classification = "NONCROSSER_DOWNSIDE_PROPAGATION_ONLY"
    elif crossing_pass:
        classification = "CROSSER_CHANNEL_WITHOUT_LOCALIZATION"
    else:
        classification = "AGGREGATE_RESPONSE_NOT_MEMBERSHIP_RESOLVED"
    terminal = audit[audit["audit_type"] == "terminal_diagnostic"]
    terminal_diagnostics = {
        channel: {
            str(horizon): _median(
                terminal[
                    (terminal["channel"] == channel)
                    & (terminal["horizon"] == horizon)
                ]["partial_rho"]
            )
            for horizon in (1, 3, 5)
        }
        for channel in ("CROSSER_DOWNSIDE", "NONCROSSER_DOWNSIDE")
    }
    return {"channels": summaries, "terminal_diagnostics": terminal_diagnostics}, classification


def _write_report(result: dict[str, Any]) -> None:
    channels = result["evaluation"]["channels"]
    lines = [
        "# MKT-FORMDEPTH-PROP-001 response topology",
        "",
        "## Decision",
        "",
        f"`{result['classification']}`",
        "",
        "This is membership-resolved market association topology only. It is not",
        "causal, an entry predictor, a tradable arm portfolio, a habitat, or a rule.",
        "",
        "## Fixed support",
        "",
        f"- complete five-control rows: {result['support']['complete_five_control_rows']:,}",
        f"- minimum rows per cell: {result['support']['minimum_complete_rows_per_cell']:,}",
        f"- joint information clock: {result['joint_information_clock']}",
        "",
        "## Downside channels",
        "",
    ]
    for channel in (
        "CROSSER_DOWNSIDE",
        "NONCROSSER_DOWNSIDE",
        "CROSSER_MINUS_NONCROSSER",
    ):
        item = channels[channel]
        tail_gap = item["median_tail_residual_gap"]
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
                f"- median controlled PIT-tail residual gap: {tail_gap:.6f}",
                f"- checks: {item['checks']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Terminal diagnostics",
            "",
            f"{result['evaluation']['terminal_diagnostics']}",
            "",
            "Terminal responses are diagnostic-only and cannot rescue a downside",
            "classification. HAB-CHX-FORMDEPTH-001 remains closed. Strategy fields,",
            "post-2023 data, and CY-011 were not read.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    helper = _import_attribution(spec)
    _guard(spec, started)
    panel, support = _load_panel(spec)
    audit = _audit(panel, spec, helper)
    evaluation, classification = _evaluate(audit, spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_MEMBERSHIP_RESOLVED_MARKET_RESPONSE_TOPOLOGY",
        "classification": classification,
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "joint_information_clock": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
        "support": support,
        "evaluation": evaluation,
        "terminal_can_promote": False,
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
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(result)
    _guard(spec, started)
    durable = sum(
        path.stat().st_size for path in (PANEL_PATH, AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise PropagationError("durable output ceiling breached")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
