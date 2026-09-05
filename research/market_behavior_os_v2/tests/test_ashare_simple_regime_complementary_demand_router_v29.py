from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_ashare_simple_regime_complementary_demand_router_v29 as v29  # noqa: E402


def _daily(count: int = 20) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=count)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "cal_idx": range(count),
            "symbol": "600000.SH",
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "trade_status": 1,
            "current_day_data_tradable": True,
            "up_limit_price": 11.0,
            "down_limit_price": 9.0,
            "market_rule_valid": True,
            "corporate_action_valid": True,
            "corporate_action_blocking": False,
            "history_valid": True,
            "current_valid": True,
            "hard_valid": True,
            "invalid_step_cum": 0.0,
            "coord_open": 10.0,
            "coord_high": 10.5,
            "coord_low": 9.5,
            "coord_close": 10.0,
        }
    )


def _candidate(signal_date: pd.Timestamp) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "V29B|TEST",
                "symbol": "600000.SH",
                "sleeve": "MAIN",
                "signal_date": signal_date,
                "cal_idx": 0,
                "invalid_step_cum": 0.0,
            }
        ]
    )


def test_target_starts_after_entry_and_preserves_t1() -> None:
    daily = _daily()
    daily.loc[1, "coord_high"] = 12.0
    daily.loc[2, "coord_high"] = 12.0
    result = v29.build_outcome_batch(_candidate(daily.trade_date.iloc[0]), daily)
    row = result.iloc[0]
    assert row.status == "COMPLETED"
    assert row.entry_cal_idx == 1
    assert row.exit_cal_idx == 2
    assert row.exit_reason == "TARGET_15"
    assert abs(row.net_return - 0.146) < 1e-12


def test_h15_decision_exits_at_next_legal_open() -> None:
    daily = _daily(25)
    result = v29.build_outcome_batch(_candidate(daily.trade_date.iloc[0]), daily)
    row = result.iloc[0]
    assert row.entry_cal_idx == 1
    assert row.exit_cal_idx == 17
    assert row.exit_reason == "H15_TIME_STOP"
    assert row.holding_sessions == 16


def test_limit_locked_entry_is_skipped_until_legal() -> None:
    daily = _daily()
    daily.loc[1, "open"] = 11.0
    daily.loc[1, "coord_open"] = 11.0
    result = v29.build_outcome_batch(_candidate(daily.trade_date.iloc[0]), daily)
    assert result.iloc[0].entry_cal_idx == 2


def test_contract_has_exactly_five_bull_condition_groups() -> None:
    contract = json.loads(v29.CONTRACT.read_text(encoding="utf-8"))
    groups = contract["simple_bull_five_groups"]
    assert len([key for key in groups if key[0].isdigit()]) == 5
    assert contract["governance"]["expanded_bull_outcomes_opened_before_freeze"] is False
    assert contract["governance"]["new_threshold_search"] is False
