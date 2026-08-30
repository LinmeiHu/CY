from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_vol_trans_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_003", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
transition = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(transition)


def test_control_and_inherited_spec_identities() -> None:
    scientific, control = transition._load_specs()
    assert transition.sha256_file(transition.CONTROL_SPEC_PATH) == (
        transition.EXPECTED_CONTROL_SPEC_SHA256
    )
    assert transition.sha256_file(transition.base.SPEC_PATH) == control[
        "inherits_scientific_design_sha256"
    ]
    assert transition.sha256_file(transition.retry.CONTROL_SPEC_PATH) == control[
        "predecessor_control_spec_sha256"
    ]
    assert scientific["population"]["future_shift_sessions"] == 25


def test_complete_support_audit_passes_before_estimation() -> None:
    scientific, _ = transition._load_specs()
    base_panel, trend = transition.base.load_bound_inputs(scientific)
    panel = transition.base.construct_future_state(base_panel, scientific)
    audit = transition.preaudit_support(panel, trend, scientific)
    assert min(audit["baseline_minimum_support"].values()) >= 150
    assert min(audit["direction_modifier_minimum_low"].values()) >= 120
    assert min(audit["direction_modifier_minimum_high"].values()) >= 120
    assert min(audit["discovery_modifier_minimum_low"].values()) >= 120
    assert min(audit["discovery_modifier_minimum_high"].values()) >= 120


def test_discovery_grouping_retains_views_and_denominators() -> None:
    scientific, _ = transition._load_specs()
    base_panel, _ = transition.base.load_bound_inputs(scientific)
    panel = transition.base.construct_future_state(base_panel, scientific)
    block = transition.base._block_frame(panel, scientific, "block_a_reused")
    assert block["market_view"].nunique() == 4
    assert block["denominator"].nunique() == 2
    assert block.groupby("market_view")["denominator"].nunique().eq(2).all()
    assert transition._effective_gate_spec(scientific)["habitat_modifiers"]["discovery"][
        "sign_support_minimum"
    ] == 3


def test_completed_artifact_boundaries_when_present() -> None:
    if not transition.RESULT_PATH.exists() or not transition.PANEL_PATH.exists():
        return
    result = json.loads(transition.RESULT_PATH.read_text(encoding="utf-8"))
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
