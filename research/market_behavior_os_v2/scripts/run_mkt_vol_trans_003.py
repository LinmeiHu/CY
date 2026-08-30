#!/usr/bin/env python3
"""Final support-correct execution of continuous volatility transitions."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RETRY_SCRIPT = PROGRAM / "scripts/run_mkt_vol_trans_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_002_base", RETRY_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-VOL-TRANS-002 support runner")
retry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(retry)
base = retry.base

CONTROL_SPEC_PATH = PROGRAM / "experiments/MKT-VOL-TRANS-003_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-003_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-003_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-VOL-TRANS-003_dynamics.md"
EXPECTED_CONTROL_SPEC_SHA256 = "a90dd17f7ae861a4627e9f6ccd2c78ba5edcade7393e2f4af6281249057e73e1"


class VolatilityTransitionFinalError(RuntimeError):
    """Fail-closed MKT-VOL-TRANS-003 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_specs() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(CONTROL_SPEC_PATH) != EXPECTED_CONTROL_SPEC_SHA256:
        raise VolatilityTransitionFinalError("control spec identity mismatch")
    control = json.loads(CONTROL_SPEC_PATH.read_text(encoding="utf-8"))
    if control["status"] != "FROZEN_BEFORE_FUTURE_VOLATILITY_STATE_CONSTRUCTION":
        raise VolatilityTransitionFinalError("control spec is not frozen")
    if sha256_file(base.SPEC_PATH) != control["inherits_scientific_design_sha256"]:
        raise VolatilityTransitionFinalError("scientific spec identity mismatch")
    if sha256_file(retry.CONTROL_SPEC_PATH) != control["predecessor_control_spec_sha256"]:
        raise VolatilityTransitionFinalError("predecessor control identity mismatch")
    scientific = base._load_spec()
    corrections = control["only_estimator_corrections"]
    if not corrections["complete_support_audit_before_any_estimate"]:
        raise VolatilityTransitionFinalError("pre-estimate support audit changed")
    return scientific, control


def preaudit_support(
    panel: pd.DataFrame, trend: pd.DataFrame, scientific: dict[str, Any]
) -> dict[str, Any]:
    """Audit every 003 cell before estimating any correlation."""
    audit: dict[str, Any] = {
        "baseline_minimum_support": {},
        "baseline_phase_minimum_support": {},
        "direction_modifier_minimum_low": {},
        "direction_modifier_minimum_high": {},
        "discovery_modifier_minimum_low": {},
        "discovery_modifier_minimum_high": {},
    }
    expanded = panel.merge(trend, on="trade_date", how="inner", validate="many_to_many")
    expected = scientific["population"]["base_rows"] * len(
        scientific["population"]["direction_indices"]
    )
    if len(expanded) != expected:
        raise VolatilityTransitionFinalError("expanded support population mismatch")
    for block_name in base.BLOCK_NAMES:
        base_block = base._block_frame(panel, scientific, block_name)
        direction_block = base._block_frame(expanded, scientific, block_name)
        for coordinate in base.COORDINATES:
            predictor, response, controls = base._baseline_fields(scientific, coordinate)
            required = [predictor, response, *controls]
            supports: list[int] = []
            phase_supports: list[int] = []
            for _, group in base._analysis_groups(base_block, coordinate):
                count = retry._complete_count(group, required)
                if count < base._minimum_support(scientific, coordinate):
                    raise VolatilityTransitionFinalError(
                        f"baseline support audit failed: {block_name}:{coordinate}:{count}"
                    )
                phase_count = len(
                    base._phase_sample(
                        group, required, int(scientific["population"]["phase_stride"])
                    )
                )
                if phase_count <= len(controls) + 3:
                    raise VolatilityTransitionFinalError(
                        f"baseline phase audit failed: {block_name}:{coordinate}:{phase_count}"
                    )
                supports.append(count)
                phase_supports.append(int(phase_count))
            key = f"{block_name}:{coordinate}"
            audit["baseline_minimum_support"][key] = min(supports)
            audit["baseline_phase_minimum_support"][key] = min(phase_supports)
        for split_name in base.SPLIT_NAMES:
            for coordinate in base.MODIFIER_COORDINATES:
                direction_low: list[int] = []
                direction_high: list[int] = []
                for _, group in direction_block.groupby(
                    ["index_symbol", "denominator"], sort=True
                ):
                    low, high, minimum = retry._modifier_cell_counts(
                        group,
                        scientific,
                        coordinate,
                        "direction_return_60_pit_3y_pct",
                        split_name,
                    )
                    if min(low, high) < minimum:
                        raise VolatilityTransitionFinalError(
                            f"direction support audit failed: {block_name}:{split_name}:"
                            f"{coordinate}:{low}:{high}:{minimum}"
                        )
                    direction_low.append(low)
                    direction_high.append(high)
                key = f"{block_name}:{split_name}:{coordinate}"
                audit["direction_modifier_minimum_low"][key] = min(direction_low)
                audit["direction_modifier_minimum_high"][key] = min(direction_high)

                discovery_low: list[int] = []
                discovery_high: list[int] = []
                for _, group in base_block.groupby("market_view", sort=True):
                    low, high, minimum = retry._modifier_cell_counts(
                        group,
                        scientific,
                        coordinate,
                        "breadth_net_new_high_low60_pit_3y_pct",
                        split_name,
                    )
                    if min(low, high) < minimum:
                        raise VolatilityTransitionFinalError(
                            f"discovery support audit failed: {block_name}:{split_name}:"
                            f"{coordinate}:{low}:{high}:{minimum}"
                        )
                    discovery_low.append(low)
                    discovery_high.append(high)
                audit["discovery_modifier_minimum_low"][key] = min(discovery_low)
                audit["discovery_modifier_minimum_high"][key] = min(discovery_high)
    return audit


def _discovery_modifier_estimate(
    frame: pd.DataFrame,
    scientific: dict[str, Any],
    coordinate: str,
    split_name: str,
) -> dict[str, Any]:
    habitat = "breadth_net_new_high_low60_pit_3y_pct"
    effects: dict[str, float] = {}
    supports: dict[str, Any] = {}
    cell_rhos: dict[str, Any] = {}
    for view, group in frame.groupby("market_view", sort=True):
        effect, cell_support, rhos = base._cell_difference(
            group, scientific, coordinate, habitat, split_name
        )
        effects[str(view)] = effect
        supports[str(view)] = cell_support
        cell_rhos[str(view)] = rhos
    if len(effects) != 4:
        raise VolatilityTransitionFinalError("discovery view count changed")
    return base._summarize_modifier(effects, supports, cell_rhos)


def _effective_gate_spec(scientific: dict[str, Any]) -> dict[str, Any]:
    effective = copy.deepcopy(scientific)
    effective["habitat_modifiers"]["discovery"]["sign_support_minimum"] = 3
    return effective


def analyze(
    panel: pd.DataFrame, trend: pd.DataFrame, scientific: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    support_audit = preaudit_support(panel, trend, scientific)
    expanded = panel.merge(trend, on="trade_date", how="inner", validate="many_to_many")
    baseline_blocks: dict[str, Any] = {}
    modifiers: dict[str, Any] = {"direction": {}, "discovery": {}}
    for block_name in base.BLOCK_NAMES:
        base_block = base._block_frame(panel, scientific, block_name)
        direction_block = base._block_frame(expanded, scientific, block_name)
        baseline_blocks[block_name] = {
            coordinate: base._baseline_estimate(base_block, scientific, coordinate)
            for coordinate in base.COORDINATES
        }
        for split_name in base.SPLIT_NAMES:
            modifiers["direction"].setdefault(block_name, {})[split_name] = {
                coordinate: retry._direction_modifier_estimate(
                    direction_block, scientific, coordinate, split_name
                )
                for coordinate in base.MODIFIER_COORDINATES
            }
            modifiers["discovery"].setdefault(block_name, {})[split_name] = {
                coordinate: _discovery_modifier_estimate(
                    base_block, scientific, coordinate, split_name
                )
                for coordinate in base.MODIFIER_COORDINATES
            }
    baseline = {
        "blocks": baseline_blocks,
        **base._baseline_gate(scientific, baseline_blocks),
    }
    effective = _effective_gate_spec(scientific)
    for name in modifiers:
        modifiers[name].update(base._modifier_gate(effective, name, modifiers[name]))
    return baseline, modifiers, support_audit


def run() -> dict[str, Any]:
    scientific, control = _load_specs()
    base_panel, trend = base.load_bound_inputs(scientific)
    panel = base.construct_future_state(base_panel, scientific)
    baseline, modifiers, support_audit = analyze(panel, trend, scientific)
    classifications = {
        "baseline_transition_dynamic": bool(baseline["baseline_gate_pass"]),
        "direction_modifier": bool(modifiers["direction"]["modifier_gate_pass"]),
        "discovery_modifier": bool(modifiers["discovery"]["modifier_gate_pass"]),
    }
    passed = [name for name, value in classifications.items() if value]
    failed = [name for name, value in classifications.items() if not value]

    output = base._direction_wide(panel, trend, scientific)
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output["future_trade_date"] = output["future_trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": control["experiment_id"],
        "status": f"COMPLETE_{len(passed)}_OF_3_TRANSITION_CLAIMS_PASS",
        "evidence_label": "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION",
        "confirmation_status": "INDEPENDENT_FUTURE_TIME_REQUIRED",
        "usefulness_claim": "NONE",
        "future_market_volatility_state_fields_read": [scientific["response"]],
        "future_price_return_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_volatility_roles_read": [],
        "failed_breadth_roles_read": [],
        "failed_trend_roles_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "base_rows": int(len(base_panel)),
            "direction_rows": int(len(trend)),
            "expanded_diagnostic_rows": int(len(base_panel) * trend["index_symbol"].nunique()),
            "base_groups": int(base_panel.groupby(["market_view", "denominator"]).ngroups),
            "direction_indices": int(trend["index_symbol"].nunique()),
            "discovery_views": int(base_panel["market_view"].nunique()),
            "first_predictor_date": str(panel["trade_date"].min().date()),
            "last_predictor_with_response": str(
                panel.loc[panel["future_trade_date"].notna(), "trade_date"].max().date()
            ),
            "last_response_date": str(panel["future_trade_date"].max().date()),
        },
        "support_audit": support_audit,
        "baseline_diagnostics": baseline,
        "modifier_diagnostics": modifiers,
        "transition_decision": {
            "passing_claims": passed,
            "failing_claims": failed,
            **classifications,
        },
        "hashes": {
            "control_spec_sha256": sha256_file(CONTROL_SPEC_PATH),
            "predecessor_control_spec_sha256": sha256_file(retry.CONTROL_SPEC_PATH),
            "scientific_spec_sha256": sha256_file(base.SPEC_PATH),
            "volatility_panel_sha256": scientific["inputs"]["volatility_panel"]["sha256"],
            "volatility_result_sha256": scientific["inputs"]["volatility_result"]["sha256"],
            "breadth_panel_sha256": scientific["inputs"]["breadth_panel"]["sha256"],
            "breadth_result_sha256": scientific["inputs"]["breadth_result"]["sha256"],
            "trend_panel_sha256": scientific["inputs"]["trend_panel"]["sha256"],
            "trend_result_sha256": scientific["inputs"]["trend_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = base._clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    report = base._render_report(result).replace("MKT-VOL-TRANS-001", "MKT-VOL-TRANS-003")
    REPORT_PATH.write_text(report, encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "transition_decision": completed["transition_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
