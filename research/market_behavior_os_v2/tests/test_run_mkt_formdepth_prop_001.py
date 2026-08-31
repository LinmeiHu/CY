from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_prop_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_prop_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_topology_boundary() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["adverse_only_for_classification"] is True
    assert spec["response"]["terminal_cannot_rescue"] is True
    assert spec["controls"] == [
        "breadth_net_new_high_low60_pit_3y_pct",
        "realized_volatility_median20_pit_3y_pct",
        "median_signed_limit_utilization",
        "open_close_log_return__median",
        "intraday_log_range__median",
    ]


def test_corrected_membership_domain_is_exact_and_outcome_blind() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-002_result.json").read_text()
    )
    assert result["status"] == "COMPLETE_MEMBERSHIP_RESPONSE_DOMAIN_ADEQUACY"
    assert result["population"]["topology_complete_cells"] == 11289
    assert result["response_domain"]["minimum_topology_complete_dates_per_cell_year"] == 202
    assert result["response_domain"]["gates"]["anchor_and_response_exhaustion"] is True
    assert result["response_domain"]["gates"]["broad_response_identity"] == (
        "IMMUTABLE_BOUND_PANEL_HASH"
    )
    assert result["scalar_reconstruction"]["cases_per_arm"] == {
        "crossing": 5,
        "noncrossing": 5,
    }
    assert result["state_outcome_estimates_computed"] is False
    assert result["topology_classification_computed"] is False


def test_localized_classification_and_near_boundary_are_preserved() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-001_result.json").read_text()
    )
    channels = result["evaluation"]["channels"]
    assert result["classification"] == "LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY"
    assert channels["CROSSER_DOWNSIDE"]["pass"] is True
    assert channels["CROSSER_MINUS_NONCROSSER"]["pass"] is True
    assert channels["NONCROSSER_DOWNSIDE"]["pass"] is False
    assert channels["NONCROSSER_DOWNSIDE"]["checks"]["primary"] is False
    assert channels["NONCROSSER_DOWNSIDE"]["median_h3_partial_rho"] > -0.1
    assert result["terminal_can_promote"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
