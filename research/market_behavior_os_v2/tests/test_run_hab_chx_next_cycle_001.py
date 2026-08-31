from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"


def _result(name: str) -> dict:
    return json.loads((PROGRAM / f"artifacts/{name}_result.json").read_text())


def test_all_four_frozen_runner_specs_retain_bound_identity() -> None:
    runners = (
        "run_hab_chx_rank_info_001.py",
        "run_hab_chx_rank_model_001.py",
        "run_hab_chx_exit_screen_001.py",
        "run_hab_chx_minvol_cost_001.py",
    )
    for offset, runner in enumerate(runners):
        spec = importlib.util.spec_from_file_location(
            f"next_cycle_runner_{offset}", PROGRAM / "scripts" / runner
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        loaded = module._load_spec()
        assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
        assert loaded["experiment_id"].endswith("001")


def test_candidate_panel_is_fixed_pre2024_and_outcomes_are_not_inputs() -> None:
    spec = json.loads(
        (PROGRAM / "experiments/HAB-CHX-RANK-INFO-001_spec.json").read_text()
    )
    result = _result("HAB-CHX-RANK-INFO-001")
    panel = pd.read_csv(
        PROGRAM / "artifacts/HAB-CHX-RANK-INFO-001_candidate_panel.csv",
        parse_dates=["trade_date"],
    )
    descriptors = [
        feature
        for family in ("trend_relative_strength", "supply_demand", "risk_path_setup")
        for feature in spec["descriptors"][family]
    ]
    forbidden = {
        "forward_return_5",
        "forward_return_20",
        "mfe_20",
        "mae_20",
        "actual_completed_trade_return",
        "selected_by_current_system",
        "next_open_price",
    }
    assert len(descriptors) == 15
    assert forbidden.isdisjoint(descriptors)
    assert result["counts"]["candidate_rows"] == len(panel) == 398
    assert result["counts"]["complete_outcome_rows"] == 397
    assert result["counts"]["candidate_dates"] == 225
    assert result["counts"]["multi_candidate_dates"] == 75
    assert result["descriptors"]["rs_score"]["information_role"] == (
        "EXISTING_BASELINE_CONDITIONAL"
    )
    assert "STRONG_STANDALONE" not in {
        row["information_role"] for row in result["descriptors"].values()
    }
    assert panel.trade_date.max() <= pd.Timestamp("2023-12-31")
    assert panel.decision_at.str.endswith("T15:00:00+08:00").all()
    assert result["claim_boundary"]["post_2023_rows_read"] is False
    assert result["claim_boundary"]["cy011_read"] is False


def test_small_ranking_models_do_not_clear_the_engine_replay_gate() -> None:
    spec = json.loads(
        (PROGRAM / "experiments/HAB-CHX-RANK-MODEL-001_spec.json").read_text()
    )
    result = _result("HAB-CHX-RANK-MODEL-001")
    assert len(spec["equal_weight_bundles"]) == 4
    assert set(spec["fixed_models"]) == {"RIDGE_ALPHA_10", "TREE_DEPTH_2"}
    assert result["engine_replay_shortlist"] == []
    assert result["decision"] == "NO_RANKING_MODEL_CLEARED_PREDECLARED_REPLAY_GATE"
    assert all(
        role == "NO_ENGINE_REPLAY"
        for name, role in result["information_roles"].items()
        if name != "BASELINE_RS_SCORE"
    )
    consumed = result["evaluations"]["RIDGE_ALPHA_10"]["blocks"][
        "consumed_2022_2023"
    ]["top1"]
    baseline = result["evaluations"]["BASELINE_RS_SCORE"]["blocks"][
        "consumed_2022_2023"
    ]["top1"]
    assert consumed["severe_loss_rate"] < baseline["severe_loss_rate"]
    assert result["claim_boundary"]["future_fields_used_as_predictors"] is False


def test_exit_screen_preserves_failure_and_runs_no_replay() -> None:
    result = _result("HAB-CHX-EXIT-SCREEN-001")
    assert result["population"]["development_2018_2021"]["simple_cycles"] == 53
    assert result["population"]["consumed_2022_2023"]["simple_cycles"] == 28
    assert result["replay_candidate"] is None
    assert result["decision"] == "EXIT_REMAINS_UNRESOLVED"
    assert set(result["evaluations"]) == {
        "MA20_X2",
        "MA30_X1",
        "MA20_X1",
        "MA40_X1",
    }
    assert set(result["information_roles"].values()) == {"NO_EXIT_REPLAY"}
    for evaluation in result["evaluations"].values():
        assert evaluation["development_2018_2021"]["fail_closed_cycles"] == 0
        assert evaluation["consumed_2022_2023"]["fail_closed_cycles"] == 0


def test_minute_vol_overlay_is_downgraded_by_matched_cost_stress() -> None:
    result = _result("HAB-CHX-MINVOL-COST-001")
    assert result["decision"] == "DOWNGRADED_COST_SENSITIVE_RISK_OVERLAY"
    assert result["all_predeclared_checks_pass"] is False
    cost20 = result["stress_results"]["20"]["comparisons"][
        "development_2018_2021"
    ]
    cost30 = result["stress_results"]["30"]["comparisons"][
        "development_2018_2021"
    ]
    assert cost20["overlay_minus_baseline"]["total_return"] > 0
    assert cost20["checks"]["material_total_return_benefit"] is False
    assert cost30["overlay_minus_baseline"]["total_return"] < 0
    assert cost30["checks"]["total_return_improves"] is False
    for cost in (20, 30):
        for arm in ("SAME_COST_BASELINE", "MINVOL_HIGH_HALF_GROSS"):
            for block in ("development_2018_2021", "consumed_2022_2023"):
                summary = json.loads(
                    (
                        PROGRAM
                        / f"artifacts/HAB-CHX-MINVOL-COST-001/{cost}BPS/{arm}/{block}"
                        / "engine_summary.json"
                    ).read_text()
                )
                assert summary["execution"]["transaction_cost_bps_per_side"] == cost
    assert result["claim_boundary"]["post_2023_rows_read"] is False
    assert result["claim_boundary"]["cy011_read"] is False
