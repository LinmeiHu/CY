#!/usr/bin/env python3
"""Output-schema-only retry of final continuous volatility transitions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
FINAL_SCRIPT = PROGRAM / "scripts/run_mkt_vol_trans_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_003_base", FINAL_SCRIPT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-VOL-TRANS-003 final estimator")
final = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(final)
base = final.base
retry = final.retry

CONTROL_SPEC_PATH = PROGRAM / "experiments/MKT-VOL-TRANS-004_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-004_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-004_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-VOL-TRANS-004_dynamics.md"
EXPECTED_CONTROL_SPEC_SHA256 = "e2859b62539f12c5112bd3bbb845c7d47695fbfd104bd3f126552ba231ccc9cb"


class VolatilityTransitionOutputError(RuntimeError):
    """Fail-closed MKT-VOL-TRANS-004 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_specs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if sha256_file(CONTROL_SPEC_PATH) != EXPECTED_CONTROL_SPEC_SHA256:
        raise VolatilityTransitionOutputError("output control spec identity mismatch")
    output_control = json.loads(CONTROL_SPEC_PATH.read_text(encoding="utf-8"))
    if output_control["status"] != "FROZEN_BEFORE_ACCEPTED_RESULT_SERIALIZATION":
        raise VolatilityTransitionOutputError("output control spec is not frozen")
    scientific, final_control = final._load_specs()
    if sha256_file(base.SPEC_PATH) != output_control["inherits_scientific_design_sha256"]:
        raise VolatilityTransitionOutputError("scientific spec identity mismatch")
    if sha256_file(final.CONTROL_SPEC_PATH) != output_control[
        "inherits_final_control_spec_sha256"
    ]:
        raise VolatilityTransitionOutputError("final control spec identity mismatch")
    return scientific, final_control, output_control


def run() -> dict[str, Any]:
    scientific, final_control, output_control = _load_specs()
    base_panel, trend = base.load_bound_inputs(scientific)
    panel = base.construct_future_state(base_panel, scientific)
    baseline, modifiers, support_audit = final.analyze(panel, trend, scientific)
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
    scientific_hash = sha256_file(base.SPEC_PATH)
    result: dict[str, Any] = {
        "experiment_id": output_control["experiment_id"],
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
            "spec_sha256": scientific_hash,
            "scientific_spec_sha256": scientific_hash,
            "final_control_spec_sha256": sha256_file(final.CONTROL_SPEC_PATH),
            "output_control_spec_sha256": sha256_file(CONTROL_SPEC_PATH),
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
    report = base._render_report(result).replace("MKT-VOL-TRANS-001", "MKT-VOL-TRANS-004")
    REPORT_PATH.write_text(report, encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "transition_decision": completed["transition_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
