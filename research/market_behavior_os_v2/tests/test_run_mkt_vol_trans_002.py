from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_vol_trans_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_vol_trans_002", SCRIPT)
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
    assert scientific["population"]["future_shift_sessions"] == 25
    assert control["only_estimator_correction"][
        "complete_support_audit_before_any_estimate"
    ] is True


def test_complete_support_audit_fails_closed_before_estimation() -> None:
    scientific, _ = transition._load_specs()
    base_panel, trend = transition.base.load_bound_inputs(scientific)
    panel = transition.base.construct_future_state(base_panel, scientific)
    with pytest.raises(
        transition.VolatilityTransitionRetryError,
        match=r"discovery support audit failed: block_a_reused:primary:raw:127:198:150",
    ):
        transition.preaudit_support(panel, trend, scientific)


def test_direction_grouping_retains_every_view_index_and_denominator() -> None:
    scientific, _ = transition._load_specs()
    base_panel, trend = transition.base.load_bound_inputs(scientific)
    panel = transition.base.construct_future_state(base_panel, scientific)
    block = transition.base._block_frame(
        panel.merge(trend, on="trade_date", how="inner", validate="many_to_many"),
        scientific,
        "block_a_reused",
    )
    assert block["index_symbol"].nunique() == 6
    assert block["market_view"].nunique() == 4
    assert block["denominator"].nunique() == 2
    assert block.groupby(["index_symbol", "denominator"])["market_view"].nunique().eq(4).all()


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
