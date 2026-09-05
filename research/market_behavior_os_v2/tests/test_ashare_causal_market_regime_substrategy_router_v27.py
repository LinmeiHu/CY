from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_ashare_causal_market_regime_substrategy_router_v27 as v27  # noqa: E402


def test_deep_bear_gate_requires_stock_depth_or_exhausted_selling() -> None:
    frame = pd.DataFrame(
        {
            "market_median_ret60": [-0.05, -0.06, -0.06, -0.049],
            "exact_prior20_return": [-0.149, -0.15, -0.10, -0.05],
            "last5_downside_turnover": [0.011, 0.02, 0.01, 0.03],
        }
    )
    mask = v27.slow_candidate_masks(frame)["DEEP_MARKET_REQUIRES_EITHER"]
    assert mask.tolist() == [False, True, True, True]


def test_intraday_target_does_not_release_capacity_at_same_open() -> None:
    date = pd.Timestamp("2023-01-10")
    active = {
        "target_same_day": SimpleNamespace(
            exit_date=date, exit_reason="TARGET_15"
        ),
        "time_stop_same_day": SimpleNamespace(
            exit_date=date, exit_reason="H20_TIME_STOP"
        ),
        "target_prior_day": SimpleNamespace(
            exit_date=date - pd.Timedelta(days=1), exit_reason="TARGET_10"
        ),
    }
    released = v27.release_before_open(active, date)
    assert released == ["time_stop_same_day", "target_prior_day"]
    assert list(active) == ["target_same_day"]


def test_candidate_selection_is_development_only_and_frozen() -> None:
    slow = v27.load_slow_base()
    table = v27.evaluate_slow_candidates(slow)
    selected = table.loc[table.selected, "candidate"].tolist()
    assert selected == ["DEEP_MARKET_REQUIRES_EITHER"]

    changed = slow.copy()
    changed.loc[changed.signal_date.gt(v27.SELECTION_END), "net_return"] = -999.0
    changed_table = v27.evaluate_slow_candidates(changed)
    pd.testing.assert_frame_equal(table, changed_table)


def test_full_router_reproduction_passes_causal_and_goal_gates() -> None:
    result = v27.run()
    assert result["verdict"] == (
        "CAUSAL_MARKET_REGIME_SUBSTRATEGY_ROUTER_HISTORICAL_GOAL_MET"
    )
    assert all(result["gates"].values())
    audit = result["audit"]
    for key in (
        "challenge_rows_used_for_candidate_selection_count",
        "post_2023_signal_count",
        "post_2023_exit_count",
        "missing_signal_decision_count",
        "signal_available_after_decision_count",
        "market_state_after_signal_decision_count",
        "slow_feature_available_after_decision_count",
        "slow_market_state_after_decision_count",
        "event_id_duplicate_count",
        "same_symbol_signal_date_duplicate_count",
        "entry_at_or_before_signal_count",
        "exit_at_or_before_entry_count",
        "t1_same_day_exit_count",
        "true_duplicate_active_symbol_count",
        "rank_missing_count",
        "entry_execution_violation_count",
        "target_execution_violation_count",
        "open_exit_execution_violation_count",
        "corporate_action_coordinate_lineage_violation_count",
        "negative_cash_count",
        "open_position_at_end_count",
    ):
        assert audit[key] == 0
