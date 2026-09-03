from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_v6_full_signal_strategy_research_v1 as research,
)


def test_frozen_entry_and_feature_families_are_complete() -> None:
    assert len(research.LEVELS) == 7
    assert len(research.CONFIRMATIONS) == 5
    assert len(research.LEVELS) * len(research.CONFIRMATIONS) == 35
    features = research.feature_contract()
    assert len(features) == 163
    assert {row["family"] for row in features} == {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    assert len({row["name"] for row in features}) == len(features)


def test_trigger_levels_use_only_frozen_normalizations() -> None:
    lower, upper = 100.0, 110.0
    assert research.trigger_level(lower, upper, "ABS_1P0") == 101.0
    assert research.trigger_level(lower, upper, "GAP_10") == 101.0
    assert research.trigger_level(lower, upper, "GAP_50") == 105.0


def test_corporate_action_exit_precedes_other_exits() -> None:
    risk = {"exit_time": pd.Timestamp("2020-01-03 09:31"), "exit_date": pd.Timestamp("2020-01-03"), "raw_price": 9.0, "cal_idx": 3}
    target = {"exit_time": pd.Timestamp("2020-01-03 10:00"), "exit_date": pd.Timestamp("2020-01-03"), "raw_price": 11.0, "cal_idx": 3}
    chosen, reason = research._choose_exit(target, None, None, risk)
    assert chosen == risk
    assert reason == "CORPORATE_ACTION_RISK"


def test_unresolved_action_block_is_fail_closed() -> None:
    actions = pd.DataFrame({"event_id": ["a"], "known_date": [pd.Timestamp("2020-01-02")]})
    blocked = {"event_id": "a"}
    later = {"exit_time": pd.Timestamp("2020-01-03")}
    earlier = {"exit_time": pd.Timestamp("2020-01-01 15:00")}
    assert research._blocked_action_precedes_exit(blocked, later, actions)
    assert research._blocked_action_precedes_exit(blocked, None, actions)
    assert not research._blocked_action_precedes_exit(blocked, earlier, actions)


def test_frozen_contract_hash_verifies() -> None:
    freeze = research.verify_feature_freeze()
    assert freeze["feature_contract_hash"] == research.EXPECTED_FEATURE_CONTRACT_HASH
    assert freeze["v6_signal_identity_changed_count"] == 0

