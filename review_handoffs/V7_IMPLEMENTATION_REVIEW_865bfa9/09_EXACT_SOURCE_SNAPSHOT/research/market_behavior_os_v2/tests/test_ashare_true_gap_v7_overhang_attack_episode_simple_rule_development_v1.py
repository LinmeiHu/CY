from __future__ import annotations

import json

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1 as research,
)


def test_frozen_family_is_bounded_and_simple() -> None:
    contract = research.rule_space_value()
    assert len(research.PENETRATION_LEVELS) * len(research.ACCEPTANCE_FORMS) == 18
    assert research.REMAINING_TARGETS == (0.010, 0.015, 0.020)
    assert research.TIME_STOPS == (5, 10, 20)
    assert len(research.FAILURE_POLICIES) == 9
    assert contract["maximum_final_conditions"] == 5
    assert contract["generated_simple_rules"]["raw_model_scores_deployable"] is False


def test_vote_rule_uses_missing_values_fail_closed() -> None:
    frame = pd.DataFrame({"a": [1.0, None, 0.0], "b": [1.0, 1.0, 0.0]})
    model = {
        "valid": True,
        "kind": "vote",
        "minimum_votes": 2,
        "conditions": [
            research._condition("a", ">=", 0.5, "TEST"),
            research._condition("b", ">=", 0.5, "TEST"),
        ],
    }
    mask, score = research.apply_rule_model(frame, model)
    assert mask.tolist() == [True, False, False]
    assert score.tolist() == [1.0, 0.5, 0.0]


def test_fold_excludes_same_gap_and_honors_20_plus_20_purge(monkeypatch) -> None:
    calendar = pd.DataFrame({"trade_date": pd.date_range("2020-01-01", periods=100, freq="D"), "cal_idx": range(100)})
    monkeypatch.setattr(research, "_calendar", lambda: calendar)
    panel = pd.DataFrame(
        {
            "attack_start_date": pd.to_datetime(["2020-01-06", "2020-01-07", "2020-02-20", "2020-02-20"]),
            "gap_id": ["SAME", "KEEP", "SAME", "TEST"],
            "entry_cal_idx": [5, 6, 50, 50],
            "outcome_valid": [True, True, True, True],
        }
    )
    fold = {"fold": "SYNTH", "start": pd.Timestamp("2020-02-20"), "end": pd.Timestamp("2020-02-20")}
    train, test, audit = research.fold_train_test(panel, fold)
    assert set(train.gap_id) == {"KEEP"}
    assert set(test.gap_id) == {"SAME", "TEST"}
    assert audit == {"same_gap_split": 0, "purge_violation": 0, "test_half_in_train": 0}


def test_legal_sell_mask_forbids_same_session() -> None:
    path = pd.DataFrame(
        {
            "cal_idx": [10, 10, 11], "invalid_step_cum": [0.0, 0.0, 0.0],
            "hard_valid": [True] * 3, "trade_status": [1] * 3,
            "current_day_data_tradable": [True] * 3, "market_rule_valid": [True] * 3,
            "corporate_action_blocking": [False] * 3, "open": [10.0] * 3,
            "down_limit_price": [9.0] * 3,
        }
    )
    assert research._legal_sell_mask(path, 10, 0.0).tolist() == [False, False, True]


def test_replay_enforces_one_gap_and_never_leverages() -> None:
    entry = pd.Timestamp("2017-01-03 09:31")
    exit_time = pd.Timestamp("2017-01-04 10:00")
    rows = []
    for symbol, score in (("000001.SZ", 0.9), ("000002.SZ", 0.8)):
        rows.append(
            {
                "entry_key": symbol, "attack_id": symbol + "|A1", "gap_id": "ONE_GAP",
                "symbol": symbol, "board": "MAIN", "entry_time": entry,
                "entry_date": entry.normalize(), "exit_time": exit_time,
                "exit_date": exit_time.normalize(), "entry_raw_price": 10.0,
                "exit_raw_price": 10.5, "cash_events_json": "[]", "outcome_valid": True,
                "simple_rule_score": score, "vacuum_score": score,
                "target_to_risk_ratio": 1.0, "net_return": 0.04,
            }
        )
    trades = pd.DataFrame(rows)
    daily = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2017-01-03", "2017-01-03", "2017-01-04", "2017-01-04"]),
            "cal_idx": [1, 1, 2, 2], "symbol": ["000001.SZ", "000002.SZ"] * 2,
            "close": [10.1, 10.1, 10.5, 10.5],
        }
    )
    replay = research.replay_v7(trades, daily, "MAIN", 10, (2017,))
    assert len(replay.accepted) == 1
    assert replay.ledger.status.tolist() == ["EXECUTED", "SKIPPED_DUPLICATE_GAP"]
    assert replay.nav.active_gaps.max() == 1
    assert replay.nav.cash.min() >= -1e-12
    assert replay.audit.get("negative_cash_or_leverage_count", 0) == 0


def test_contract_json_is_runtime_resolvable() -> None:
    # Also catches accidental JSON-style true/false names in Python contracts.
    json.dumps(research.rule_space_value(), sort_keys=True)


def test_sample_column_lookup_does_not_resolve_dataframe_method() -> None:
    frame = pd.DataFrame({"sample": ["TRAIN", "OUTER_TEST"]})
    assert research._sample_mask(frame, "OUTER_TEST").tolist() == [False, True]
