import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_long_suspension_reopening_price_discovery_mother_v1_stage_b.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("suspension_stage_b", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
stage_b = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(stage_b)


def candidate(**overrides):
    values = {
        "event_id": "000001.SZ|2015-01-05",
        "symbol": "000001.SZ",
        "sleeve": "MAIN",
        "causal_industry": "TEST",
        "pre_suspension_trade_date": pd.Timestamp("2014-12-17"),
        "pre_suspension_close": 10.0,
        "suspension_market_sessions": 10,
        "signal_date": pd.Timestamp("2015-01-05"),
        "signal_cal_idx": 100,
        "reopening_open_return": 0.05,
        "reopening_close_return": 0.04,
        "close_location": 0.7,
        "market_regime": "TRANSITION",
        "market_median_ret20": 0.01,
        "market_median_ret60": -0.01,
        "market_positive_ret20_share": 0.51,
        "market_positive_ret60_share": 0.49,
        "invalid_step_cum": 2.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def row(cal_idx, *, open_=10.0, up=11.0, down=9.0, lineage=2.0, tradable=True):
    date = pd.Timestamp("2015-01-05") + pd.offsets.BDay(cal_idx - 100)
    return {
        "event_id": "000001.SZ|2015-01-05",
        "trade_date": date,
        "cal_idx": cal_idx,
        "open": open_,
        "high": open_,
        "low": open_,
        "close": open_,
        "coord_open": open_,
        "coord_high": open_,
        "coord_low": open_,
        "coord_close": open_,
        "invalid_step_cum": lineage,
        "coordinate_factor": 1.0,
        "trade_status": int(tradable),
        "current_day_data_tradable": tradable,
        "current_valid": tradable,
        "market_rule_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": up,
        "down_limit_price": down,
        "available_at": date,
        "decision_at": date,
    }


def test_entry_cannot_fill_on_signal_or_limit_up_open():
    path = pd.DataFrame(
        [
            row(101, open_=11.0, up=11.0),
            row(102, open_=10.5),
            row(122, open_=12.0),
        ]
    )
    result = stage_b.replay_one(candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 102


def test_h20_waits_for_first_legal_sellable_open():
    path = pd.DataFrame(
        [row(101, open_=10.0)]
        + [row(idx, open_=10.0) for idx in range(102, 121)]
        + [row(121, open_=9.0, down=9.0), row(122, open_=9.5, down=9.0)]
    )
    result = stage_b.replay_one(candidate(), path)
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 101
    assert result["exit_cal_idx"] == 122
    assert result["holding_sessions"] == 21
    assert result["net_return"] == 9.5 / 10.0 - 1 - 0.004


def test_coordinate_lineage_change_fails_closed():
    path = pd.DataFrame([row(101), row(121, lineage=3.0)])
    result = stage_b.replay_one(candidate(), path)
    assert result["status"] == "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"


def test_no_entry_after_frozen_three_session_window():
    path = pd.DataFrame(
        [
            row(101, tradable=False),
            row(102, open_=11.0, up=11.0),
            row(103, tradable=False),
            row(104, open_=10.0),
        ]
    )
    result = stage_b.replay_one(candidate(), path)
    assert result["status"] == "NO_LEGAL_ENTRY"
