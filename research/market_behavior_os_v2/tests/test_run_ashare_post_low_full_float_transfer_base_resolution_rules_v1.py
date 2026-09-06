import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_post_low_full_float_transfer_base_resolution_rules_v1.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("post_low_rules_v1", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
rules = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(rules)


def candidate(**overrides):
    values = {
        "event_id": "000001.SZ|2014-12-01|2015-01-02",
        "symbol": "000001.SZ",
        "sleeve": "MAIN",
        "causal_industry": "TEST",
        "anchor_date": pd.Timestamp("2014-12-01"),
        "anchor_idx": 90,
        "anchor_low": 80.0,
        "base_ceiling": 100.0,
        "old_high": 130.0,
        "signal_date": pd.Timestamp("2015-01-02"),
        "signal_cal_idx": 100,
        "market_regime": "TRANSITION",
        "market_median_ret20": 0.02,
        "market_median_ret60": -0.02,
        "market_positive_ret20_share": 0.55,
        "market_positive_ret60_share": 0.45,
        "turnover_before_signal": 1.2,
        "anchor_age_sessions": 20,
        "target_headroom": 0.25,
        "invalid_step_cum": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def path_row(cal_idx, close, *, open_=None, high=None, low=None):
    open_ = close if open_ is None else open_
    high = max(open_, close) if high is None else high
    low = min(open_, close) if low is None else low
    return {
        "event_id": "000001.SZ|2014-12-01|2015-01-02",
        "trade_date": pd.Timestamp("2015-01-01") + pd.Timedelta(days=cal_idx - 99),
        "cal_idx": cal_idx,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "coord_open": open_,
        "coord_high": high,
        "coord_low": low,
        "coord_close": close,
        "invalid_step_cum": 1.0,
        "coordinate_factor": 1.0,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "current_valid": True,
        "market_rule_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": 120.0,
        "down_limit_price": 80.0,
        "available_at": pd.Timestamp("2015-01-01") + pd.Timedelta(days=cal_idx - 99),
        "decision_at": pd.Timestamp("2015-01-01") + pd.Timedelta(days=cal_idx - 99),
    }


def test_market_warning_is_causal_and_exact():
    normal = candidate()
    warning = candidate(
        market_median_ret20=0.081,
        market_median_ret60=-0.081,
        market_positive_ret20_share=0.701,
        market_positive_ret60_share=0.349,
    )
    boundary = candidate(market_median_ret20=0.08)
    assert not rules.violent_rebound_warning(normal)
    assert rules.violent_rebound_warning(warning)
    assert not rules.violent_rebound_warning(boundary)


def test_confirmation_rejection_does_not_enter():
    path = pd.DataFrame([path_row(101, 99.0), path_row(102, 110.0)])
    result = rules.replay_one(candidate(), path)
    assert result["status"] == "CONFIRMATION_REJECTED"
    assert "entry_date" not in result


def test_failure_close_exits_only_at_next_legal_open():
    path = pd.DataFrame(
        [
            path_row(101, 101.0, open_=100.0, high=105.0),
            path_row(102, 103.0, open_=102.0, high=106.0),
            path_row(103, 99.0, open_=104.0, high=105.0),
            path_row(104, 98.0, open_=98.0, high=100.0),
        ]
    )
    result = rules.replay_one(candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["confirmation_cal_idx"] == 101
    assert result["entry_cal_idx"] == 102
    assert result["exit_cal_idx"] == 104
    assert result["exit_reason"] == "BASE_CEILING_INVALIDATION"
    assert result["net_return"] == 98.0 / 102.0 - 1 - 0.004


def test_old_high_target_fills_after_t_plus_one():
    path = pd.DataFrame(
        [
            path_row(101, 101.0, open_=100.0, high=105.0),
            path_row(102, 105.0, open_=102.0, high=129.0),
            path_row(103, 125.0, open_=106.0, high=131.0),
        ]
    )
    result = rules.replay_one(candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 102
    assert result["exit_cal_idx"] == 103
    assert result["exit_reason"] == "OLD_HIGH_TARGET_INTRADAY"
    assert result["exit_price"] == 130.0
