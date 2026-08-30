#!/usr/bin/env python3
"""Coverage-correct execution of the frozen volatility-transition study."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
BASE_SCRIPT = PROGRAM / "scripts/run_mkt_vol_trans_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_001_base", BASE_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-VOL-TRANS-001 scientific runner")
base = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(base)

CONTROL_SPEC_PATH = PROGRAM / "experiments/MKT-VOL-TRANS-002_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-VOL-TRANS-002_dynamics.md"
EXPECTED_CONTROL_SPEC_SHA256 = "e04c720b8980be9bd69e01e442ee09db86ab1fab6b89d5ae0093f57f31a8138f"


class VolatilityTransitionRetryError(RuntimeError):
    """Fail-closed MKT-VOL-TRANS-002 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_specs() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(CONTROL_SPEC_PATH) != EXPECTED_CONTROL_SPEC_SHA256:
        raise VolatilityTransitionRetryError("control spec identity mismatch")
    control = json.loads(CONTROL_SPEC_PATH.read_text(encoding="utf-8"))
    if control["status"] != "FROZEN_BEFORE_FUTURE_VOLATILITY_STATE_CONSTRUCTION":
        raise VolatilityTransitionRetryError("control spec is not frozen")
    if sha256_file(base.SPEC_PATH) != control["inherits_scientific_design_sha256"]:
        raise VolatilityTransitionRetryError("inherited scientific spec identity mismatch")
    scientific = base._load_spec()
    correction = control["only_estimator_correction"]
    if not correction["complete_support_audit_before_any_estimate"]:
        raise VolatilityTransitionRetryError("pre-estimate support audit requirement changed")
    return scientific, control


def _complete_count(frame: pd.DataFrame, fields: list[str]) -> int:
    return int(
        len(frame[fields].replace([np.inf, -np.inf], np.nan).dropna())
    )


def _modifier_cell_counts(
    frame: pd.DataFrame,
    scientific: dict[str, Any],
    coordinate: str,
    habitat: str,
    split_name: str,
) -> tuple[int, int, int]:
    predictor, response, controls = base._baseline_fields(scientific, coordinate)
    required = [predictor, response, *controls, habitat]
    clean = frame[required].replace([np.inf, -np.inf], np.nan).dropna()
    low, high, minimum = base._split_masks(clean, habitat, scientific, split_name)
    return int(low.sum()), int(high.sum()), int(minimum)


def preaudit_support(
    panel: pd.DataFrame, trend: pd.DataFrame, scientific: dict[str, Any]
) -> dict[str, Any]:
    """Audit every frozen support cell before any correlation is estimated."""
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
        raise VolatilityTransitionRetryError("expanded support population mismatch")
    for block_name in base.BLOCK_NAMES:
        base_block = base._block_frame(panel, scientific, block_name)
        direction_block = base._block_frame(expanded, scientific, block_name)
        for coordinate in base.COORDINATES:
            predictor, response, controls = base._baseline_fields(scientific, coordinate)
            required = [predictor, response, *controls]
            supports: list[int] = []
            phase_supports: list[int] = []
            for _, group in base._analysis_groups(base_block, coordinate):
                count = _complete_count(group, required)
                if count < base._minimum_support(scientific, coordinate):
                    raise VolatilityTransitionRetryError(
                        f"baseline support audit failed: {block_name}:{coordinate}:{count}"
                    )
                phase_count = len(
                    base._phase_sample(
                        group, required, int(scientific["population"]["phase_stride"])
                    )
                )
                if phase_count <= len(controls) + 3:
                    raise VolatilityTransitionRetryError(
                        f"baseline phase audit failed: {block_name}:{coordinate}:{phase_count}"
                    )
                supports.append(count)
                phase_supports.append(int(phase_count))
            audit["baseline_minimum_support"][f"{block_name}:{coordinate}"] = min(supports)
            audit["baseline_phase_minimum_support"][f"{block_name}:{coordinate}"] = min(
                phase_supports
            )
        for split_name in base.SPLIT_NAMES:
            for coordinate in base.MODIFIER_COORDINATES:
                direction_low: list[int] = []
                direction_high: list[int] = []
                for _, group in direction_block.groupby(
                    ["index_symbol", "denominator"], sort=True
                ):
                    low, high, minimum = _modifier_cell_counts(
                        group,
                        scientific,
                        coordinate,
                        "direction_return_60_pit_3y_pct",
                        split_name,
                    )
                    if min(low, high) < minimum:
                        raise VolatilityTransitionRetryError(
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
                for _, group in base_block.groupby(
                    ["market_view", "denominator"], sort=True
                ):
                    low, high, minimum = _modifier_cell_counts(
                        group,
                        scientific,
                        coordinate,
                        "breadth_net_new_high_low60_pit_3y_pct",
                        split_name,
                    )
                    if min(low, high) < minimum:
                        raise VolatilityTransitionRetryError(
                            f"discovery support audit failed: {block_name}:{split_name}:"
                            f"{coordinate}:{low}:{high}:{minimum}"
                        )
                    discovery_low.append(low)
                    discovery_high.append(high)
                audit["discovery_modifier_minimum_low"][key] = min(discovery_low)
                audit["discovery_modifier_minimum_high"][key] = min(discovery_high)
    return audit


def _direction_modifier_estimate(
    expanded: pd.DataFrame,
    scientific: dict[str, Any],
    coordinate: str,
    split_name: str,
) -> dict[str, Any]:
    habitat = "direction_return_60_pit_3y_pct"
    effects: dict[str, float] = {}
    supports: dict[str, Any] = {}
    cell_rhos: dict[str, Any] = {}
    for index_symbol, index_frame in expanded.groupby("index_symbol", sort=True):
        denominator_effects: list[float] = []
        supports[str(index_symbol)] = {}
        cell_rhos[str(index_symbol)] = {}
        for denominator, group in index_frame.groupby("denominator", sort=True):
            effect, cell_support, rhos = base._cell_difference(
                group, scientific, coordinate, habitat, split_name
            )
            denominator_effects.append(effect)
            supports[str(index_symbol)][str(denominator)] = cell_support
            cell_rhos[str(index_symbol)][str(denominator)] = rhos
        if len(denominator_effects) != 2:
            raise VolatilityTransitionRetryError("direction denominator count changed")
        effects[str(index_symbol)] = float(
            np.median(np.asarray(denominator_effects, dtype=float))
        )
    if set(effects) != set(scientific["population"]["direction_indices"]):
        raise VolatilityTransitionRetryError("direction index set changed")
    return base._summarize_modifier(effects, supports, cell_rhos)


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
                coordinate: _direction_modifier_estimate(
                    direction_block, scientific, coordinate, split_name
                )
                for coordinate in base.MODIFIER_COORDINATES
            }
            modifiers["discovery"].setdefault(block_name, {})[split_name] = {
                coordinate: base._discovery_modifier_estimate(
                    base_block, scientific, coordinate, split_name
                )
                for coordinate in base.MODIFIER_COORDINATES
            }
    baseline = {
        "blocks": baseline_blocks,
        **base._baseline_gate(scientific, baseline_blocks),
    }
    for name in modifiers:
        modifiers[name].update(base._modifier_gate(scientific, name, modifiers[name]))
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
    report = base._render_report(result).replace("MKT-VOL-TRANS-001", "MKT-VOL-TRANS-002")
    REPORT_PATH.write_text(report, encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "transition_decision": completed["transition_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
