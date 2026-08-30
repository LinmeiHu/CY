from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_vol_trans_004.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_004", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
transition = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(transition)


def test_output_and_inherited_spec_identities() -> None:
    scientific, final_control, output_control = transition._load_specs()
    assert transition.sha256_file(transition.CONTROL_SPEC_PATH) == (
        transition.EXPECTED_CONTROL_SPEC_SHA256
    )
    assert transition.sha256_file(transition.base.SPEC_PATH) == output_control[
        "inherits_scientific_design_sha256"
    ]
    assert transition.sha256_file(transition.final.CONTROL_SPEC_PATH) == output_control[
        "inherits_final_control_spec_sha256"
    ]
    assert final_control["experiment_id"] == "MKT-VOL-TRANS-003"
    assert scientific["population"]["future_shift_sessions"] == 25


def test_completed_artifact_boundaries_when_present() -> None:
    if not transition.RESULT_PATH.exists() or not transition.PANEL_PATH.exists():
        return
    result = json.loads(transition.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["hashes"]["spec_sha256"] == result["hashes"]["scientific_spec_sha256"]
    assert result["evidence_label"] == (
        "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION"
    )
    assert result["confirmation_status"] == "INDEPENDENT_FUTURE_TIME_REQUIRED"
    for name in (
        "future_price_return_fields_read",
        "strategy_or_outcome_fields_read",
        "failed_volatility_roles_read",
        "failed_breadth_roles_read",
        "failed_trend_roles_read",
    ):
        assert result[name] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert transition.sha256_file(transition.PANEL_PATH) == result["hashes"]["panel_sha256"]
