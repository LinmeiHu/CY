#!/usr/bin/env python3
"""Estimate the frozen formation-depth crosser closing-state topology."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-CLOSE-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-001_panel.csv"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-001_response_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-CLOSE-001_topology.md"
EXPECTED_SPEC_SHA256 = "f260e1feb25bba18a82e68598ff2c3da92f1d22b93afa040d408802e6ded9c7e"


class ClosingTopologyError(RuntimeError):
    """Fail-closed closing-state response-topology error."""


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
        raise ClosingTopologyError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ClosingTopologyError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_CLOSING_STATE_RESPONSE_ESTIMATES"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_CLOSING_STATE_H1_H3_H5_RESPONSE_ONLY"
    ):
        raise ClosingTopologyError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ClosingTopologyError(f"input identity mismatch: {name}")
    closing = json.loads(_resolve(spec["inputs"]["closing_result"]["path"]).read_text())
    attribution = json.loads(
        _resolve(spec["inputs"]["attribution_result"]["path"]).read_text()
    )
    propagation = json.loads(
        _resolve(spec["inputs"]["propagation_result"]["path"]).read_text()
    )
    activation = spec["activation"]
    if closing["status"] != activation["required_closing_status"]:
        raise ClosingTopologyError("closing response domain is not activated")
    if attribution["classification"] != activation["required_attribution_classification"]:
        raise ClosingTopologyError("formation-depth attribution is not activated")
    if propagation["classification"] != activation["required_propagation_classification"]:
        raise ClosingTopologyError("localized crossing response is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise ClosingTopologyError("prohibited boundary changed")
    return spec


def _response_columns() -> list[str]:
    return [
        f"{arm}_{kind}_h{horizon}_mean"
        for arm in ("accepted", "rejected")
        for kind in ("terminal_log_return", "adverse_log_excursion")
        for horizon in (1, 3, 5)
    ]


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    closing = pd.read_csv(
        _resolve(spec["inputs"]["closing_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    activation = spec["activation"]
    if len(closing) != activation["expected_closing_panel_rows"]:
        raise ClosingTopologyError("closing panel row count changed")
    if int(closing["closing_topology_complete"].sum()) != activation[
        "expected_closing_topology_complete_rows"
    ]:
        raise ClosingTopologyError("closing-topology-complete row count changed")
    closing = closing.loc[
        closing["closing_topology_complete"], [*keys, *_response_columns()]
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
    panel = closing.merge(
        attribution[attr_columns], on=keys, how="left", validate="one_to_one"
    )
    panel = panel.dropna(subset=[state["pit"], *controls]).copy()
    if len(panel) != activation["expected_complete_five_control_rows"]:
        raise ClosingTopologyError("complete five-control row count changed")
    cell_counts = panel.groupby(keys[1:], sort=True).size()
    if len(cell_counts) != activation["expected_groups"]:
        raise ClosingTopologyError("cell count changed")
    if cell_counts.min() < activation["minimum_complete_five_control_rows_per_cell"]:
        raise ClosingTopologyError("per-cell complete support below frozen floor")
    if len(panel) < activation["minimum_complete_five_control_rows"]:
        raise ClosingTopologyError("complete support below frozen floor")
    for horizon in (1, 3, 5):
        panel[f"paired_adverse_h{horizon}"] = (
            panel[f"rejected_adverse_log_excursion_h{horizon}_mean"]
            - panel[f"accepted_adverse_log_excursion_h{horizon}_mean"]
        )
        panel[f"paired_terminal_h{horizon}"] = (
            panel[f"rejected_terminal_log_return_h{horizon}_mean"]
            - panel[f"accepted_terminal_log_return_h{horizon}_mean"]
        )
    if panel["event_year"].max() > 2023:
        raise ClosingTopologyError("post-2023 row reached closing-state analysis")
    support = {
        "closing_topology_complete_rows": len(closing),
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
        *[f"paired_adverse_h{horizon}" for horizon in (1, 3, 5)],
        *[f"paired_terminal_h{horizon}" for horizon in (1, 3, 5)],
    ]
    return panel[columns].sort_values(keys).reset_index(drop=True), support


def _adapt_panel(panel: pd.DataFrame) -> pd.DataFrame:
    adapted = panel.copy()
    for horizon in (1, 3, 5):
        adapted[f"crossing_adverse_log_excursion_h{horizon}_mean"] = adapted[
            f"rejected_adverse_log_excursion_h{horizon}_mean"
        ]
        adapted[f"noncrossing_adverse_log_excursion_h{horizon}_mean"] = adapted[
            f"accepted_adverse_log_excursion_h{horizon}_mean"
        ]
        adapted[f"crossing_terminal_log_return_h{horizon}_mean"] = adapted[
            f"rejected_terminal_log_return_h{horizon}_mean"
        ]
        adapted[f"noncrossing_terminal_log_return_h{horizon}_mean"] = adapted[
            f"accepted_terminal_log_return_h{horizon}_mean"
        ]
    return adapted


def _adapt_spec(spec: dict[str, Any]) -> dict[str, Any]:
    adapted = dict(spec)
    adapted["channels"] = {
        "CROSSER_DOWNSIDE": "rejected closing arm",
        "NONCROSSER_DOWNSIDE": "accepted closing arm",
        "CROSSER_MINUS_NONCROSSER": "rejected minus accepted",
    }
    return adapted


def _canonical_evaluation(
    evaluation: dict[str, Any], audit: pd.DataFrame
) -> tuple[dict[str, Any], pd.DataFrame, str]:
    channel_map = {
        "CROSSER_DOWNSIDE": "REJECTED_CROSSER_DOWNSIDE",
        "NONCROSSER_DOWNSIDE": "ACCEPTED_CROSSER_DOWNSIDE",
        "CROSSER_MINUS_NONCROSSER": "REJECTED_MINUS_ACCEPTED",
    }
    channels = {
        channel_map[name]: value for name, value in evaluation["channels"].items()
    }
    terminal = evaluation["terminal_diagnostics"]
    terminal_diagnostics = {
        "REJECTED_CROSSER_DOWNSIDE": terminal["CROSSER_DOWNSIDE"],
        "ACCEPTED_CROSSER_DOWNSIDE": terminal["NONCROSSER_DOWNSIDE"],
    }
    rejected_pass = channels["REJECTED_CROSSER_DOWNSIDE"]["pass"]
    accepted_pass = channels["ACCEPTED_CROSSER_DOWNSIDE"]["pass"]
    paired_pass = channels["REJECTED_MINUS_ACCEPTED"]["pass"]
    if accepted_pass and rejected_pass:
        classification = "ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE"
    elif rejected_pass and paired_pass:
        classification = "CLOSING_REJECTION_LOCALIZED_DOWNSIDE"
    elif accepted_pass and not rejected_pass:
        classification = "CLOSING_ACCEPTANCE_DOWNSIDE_ONLY"
    elif rejected_pass:
        classification = "REJECTED_CHANNEL_WITHOUT_CLOSING_LOCALIZATION"
    else:
        classification = "CROSSER_DOWNSIDE_NOT_CLOSING_STATE_RESOLVED"
    canonical_audit = audit.copy()
    canonical_audit["channel"] = canonical_audit["channel"].map(channel_map)
    return (
        {"channels": channels, "terminal_diagnostics": terminal_diagnostics},
        canonical_audit,
        classification,
    )


def _write_report(result: dict[str, Any]) -> None:
    channels = result["evaluation"]["channels"]
    lines = [
        "# MKT-FORMDEPTH-CLOSE-001 closing-state topology",
        "",
        "## Decision",
        "",
        f"`{result['classification']}`",
        "",
        "This is closing-state-resolved market association topology only. It is",
        "not causal, an entry predictor, terminal reversal, habitat, or a rule.",
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
        "ACCEPTED_CROSSER_DOWNSIDE",
        "REJECTED_CROSSER_DOWNSIDE",
        "REJECTED_MINUS_ACCEPTED",
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
                (
                    "- median controlled PIT-tail residual gap: "
                    f"{item['median_tail_residual_gap']:.6f}"
                ),
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
            "classification. Equality was conserved but not economically estimated.",
            "No strategy fields, post-2023 data, or CY-011 were read.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    topology = _import(
        _resolve(spec["inputs"]["accepted_topology_runner"]["path"]),
        "accepted_topology_close",
    )
    attribution = _import(
        _resolve(spec["inputs"]["accepted_attribution_runner"]["path"]),
        "accepted_attribution_close",
    )
    topology._guard(spec, started)
    panel, support = _load_panel(spec)
    adapted_spec = _adapt_spec(spec)
    audit = topology._audit(_adapt_panel(panel), adapted_spec, attribution)
    evaluation, _ = topology._evaluate(audit, adapted_spec)
    evaluation, audit, classification = _canonical_evaluation(evaluation, audit)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_CLOSING_STATE_RESOLVED_MARKET_RESPONSE_TOPOLOGY",
        "classification": classification,
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "joint_information_clock": spec["activation"]["joint_available_at"],
        "response_begins": spec["activation"]["response_begins"],
        "support": support,
        "evaluation": evaluation,
        "terminal_can_promote": False,
        "equality_economically_estimated": False,
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
        raise ClosingTopologyError("durable output ceiling breached")
    print(json.dumps(topology._clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
