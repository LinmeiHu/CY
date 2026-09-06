from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pandas as pd

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_first_investable_reclaim_v29r4.py"
)
SPEC = importlib.util.spec_from_file_location("v29r4", RUNNER)
assert SPEC is not None and SPEC.loader is not None
v29r4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v29r4)


def _daily() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=36)
    rows = []
    for date in dates:
        decision_at = date + pd.Timedelta(hours=15)
        rows.append(
            {
                "trade_date": date,
                "decision_at": decision_at,
                "decision_timezone": "Asia/Shanghai",
                "symbol": "000001.SZ",
                "open": 8.8,
                "high": 9.0,
                "low": 8.6,
                "close": 8.7,
                "preclose": 8.7,
                "volume": 100.0,
                "amount": 100.0,
                "trade_status": 1,
                "is_st": False,
                "up_limit_price": 11.0,
                "down_limit_price": 7.0,
                "current_day_data_tradable": True,
                "industry": "TEST",
                "corporate_action_count": 0,
                "corporate_action_blocking": False,
                "share_multiplier": 1.0,
                "cash_per_share": 0.0,
                "bar_valid": True,
                "trading_state_valid": True,
                "industry_valid": True,
                "corporate_action_valid": True,
                "market_rule_valid": True,
                "hard_valid": True,
                "available_at": decision_at,
                "snapshot_id": "SNAP",
                "daily_snapshot_id": "DAILY",
                "trading_state_snapshot_id": "STATE",
                "industry_snapshot_id": "INDUSTRY",
                "corporate_action_snapshot_id": "ACTION",
            }
        )
    frame = pd.DataFrame(rows)
    frame.loc[20, ["open", "high", "low", "close"]] = [9.8, 10.0, 9.2, 9.4]
    frame.loc[21:29, ["open", "high", "low", "close"]] = [8.8, 9.0, 8.6, 8.7]
    frame.loc[24, "low"] = 8.5
    frame.loc[27, "low"] = 8.5
    frame.loc[30, ["open", "high", "low", "close", "amount"]] = [
        8.9,
        9.15,
        8.9,
        9.1,
        300.0,
    ]
    frame.loc[31, ["open", "high", "low", "close", "amount"]] = [
        9.1,
        9.3,
        9.0,
        9.2,
        150.0,
    ]
    return frame


def _gap(daily: pd.DataFrame) -> pd.Series:
    return pd.Series(
        {
            "gap_id": "000001.SZ|2020-01-30",
            "symbol": "000001.SZ",
            "gap_date": daily.loc[20, "trade_date"],
            "signal_date": daily.loc[30, "trade_date"],
            "signal_time": daily.loc[30, "decision_at"],
            "gap_age": 10,
            "coordinate_factor": 1.0,
            "invalid_step_cum": 0.0,
            "L": 10.0,
            "pre_peak_to_gap_sessions": 30,
            "max_depth": 0.15,
            "current_depth": 0.09,
        }
    )


def test_rearms_after_first_reversal_fails_orderly_amount() -> None:
    daily = _daily()
    selected, audit, _ = v29r4.select_first_investable_for_gap(_gap(daily), daily)

    assert selected is not None
    assert selected["signal_date"] == daily.loc[31, "trade_date"]
    assert selected["signal_is_later_than_old_first_reversal"] is True
    assert audit["v13_trigger_bars"] == 2
    assert audit["orderly_gate_bars"] == 1


def test_required_snapshot_unknown_fails_closed() -> None:
    daily = _daily()
    daily.loc[31, "industry_snapshot_id"] = None

    selected, audit, _ = v29r4.select_first_investable_for_gap(_gap(daily), daily)

    assert selected is None
    assert audit["selection_status"] == "PATH_REGISTERED_LINEAGE_BREAK"
    assert audit["selection_failure_class"] == "REGISTERED_LINEAGE_INVALID"


def test_available_at_after_its_own_decision_fails_closed() -> None:
    daily = _daily()
    daily.loc[31, "available_at"] = daily.loc[31, "decision_at"] + pd.Timedelta(
        seconds=1
    )

    selected, audit, _ = v29r4.select_first_investable_for_gap(_gap(daily), daily)

    assert selected is None
    assert audit["selection_status"] == "PATH_REGISTERED_LINEAGE_BREAK"


def test_publish_no_replace_refuses_existing_target(tmp_path: Path) -> None:
    staged = tmp_path / "staged.txt"
    target = tmp_path / "target.txt"
    staged.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")

    try:
        v29r4.publish_no_replace(staged, target)
    except v29r4.V29R4Error:
        pass
    else:
        raise AssertionError("existing artifact was silently replaced")

    assert target.read_text(encoding="utf-8") == "old"
    assert staged.read_text(encoding="utf-8") == "new"


def test_uniform_raw_tick_break_is_strict_and_low_tie_uses_latest() -> None:
    daily = _daily()
    daily.loc[24, "low"] = 8.50001
    daily.loc[27, "low"] = 8.50004
    gap = _gap(daily)
    record, _ = v29r4.evaluate_signal_bar(gap, daily, 20, 30)
    assert record["days_since_low20"] == 3
    assert record["low20_raw"] == 8.50004
    assert math.isclose(
        record["recovery_from_low20"],
        daily.loc[30, "close"] / daily.loc[27, "low"] - 1.0,
    )
    assert not math.isclose(
        record["recovery_from_low20"],
        daily.loc[30, "close"] / daily.loc[24, "low"] - 1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    daily.loc[30, "close"] = daily.loc[29, "high"]
    record, _ = v29r4.evaluate_signal_bar(gap, daily, 20, 30)
    assert record["prior_high_raw_tick_break"] is False
    assert record["v13_prior_high_reversal_gate"] is False


def test_action_inside_path_is_a_coordinate_barrier() -> None:
    daily = _daily()
    daily.loc[25, "corporate_action_count"] = 1
    daily.loc[25, "cash_per_share"] = 0.05

    selected, audit, _ = v29r4.select_first_investable_for_gap(_gap(daily), daily)

    assert selected is None
    assert audit["selection_status"] == "PATH_ACTION_COORDINATE_BARRIER"
    assert audit["selection_failure_class"] == "ACTION_COORDINATE_BARRIER"


def test_unknown_action_blocking_state_fails_closed() -> None:
    daily = _daily()
    daily.loc[25, "corporate_action_blocking"] = None

    selected, audit, _ = v29r4.select_first_investable_for_gap(_gap(daily), daily)

    assert selected is None
    assert audit["selection_status"] == "PATH_ACTION_COORDINATE_BARRIER"
