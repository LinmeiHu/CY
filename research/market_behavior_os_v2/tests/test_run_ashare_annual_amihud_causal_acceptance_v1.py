import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_annual_amihud_causal_acceptance_v1.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("amihud_acceptance", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
strategy = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(strategy)


def candidate(**overrides):
    values = {
        "event_id": "000001.SZ|2014-12-31",
        "symbol": "000001.SZ",
        "sleeve": "MAIN",
        "causal_industry": "TEST",
        "portfolio_year": 2015,
        "formation_year": 2014,
        "annual_amihud": 1e-9,
        "signal_date": pd.Timestamp("2014-12-31"),
        "signal_cal_idx": 100,
        "coord_close": 10.0,
        "invalid_step_cum": 2.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def row(
    cal_idx,
    *,
    close=11.0,
    open_=11.0,
    stock_ret20=0.10,
    market_ret20=0.01,
    up=12.0,
    down=9.0,
    lineage=2.0,
    tradable=True,
):
    timestamp = pd.Timestamp("2014-12-31") + pd.offsets.BDay(cal_idx - 100)
    return {
        "event_id": "000001.SZ|2014-12-31",
        "trade_date": timestamp,
        "cal_idx": cal_idx,
        "open": open_,
        "close": close,
        "coord_open": open_,
        "coord_close": close,
        "ret20": stock_ret20,
        "invalid_step_cum": lineage,
        "coordinate_factor": 1.0,
        "trade_status": int(tradable),
        "current_day_data_tradable": tradable,
        "current_valid": tradable,
        "history_valid": True,
        "market_rule_valid": True,
        "historical_identity_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": up,
        "down_limit_price": down,
        "available_at": timestamp,
        "decision_at": timestamp,
        "market_median_ret20": market_ret20,
        "n20": 1000,
        "market_latest_source_timestamp": timestamp,
    }


def test_frozen_trigger_requires_acceptance_and_asymmetric_market_proof():
    accepted = strategy.deque([11.0] * 15 + [9.0] * 5, maxlen=20)
    assert strategy.trigger_passes(accepted, 10.0, 0.02, -0.05)
    assert not strategy.trigger_passes(accepted, 10.0, -0.01, -0.05)
    assert not strategy.trigger_passes(accepted, 10.0, 0.02, 0.03)
    only_fourteen = strategy.deque([11.0] * 14 + [9.0] * 6, maxlen=20)
    assert not strategy.trigger_passes(only_fourteen, 10.0, 0.10, 0.01)


def test_trigger_close_cannot_fill_and_limit_up_open_is_skipped():
    rows = [row(idx) for idx in range(101, 121)]
    rows.extend(
        [
            row(121, open_=12.0, up=12.0),
            row(122, open_=11.0),
        ]
    )
    rows.extend(row(idx, open_=12.0, close=12.0) for idx in range(123, 243))
    result = strategy.replay_one(candidate(), pd.DataFrame(rows))
    assert result["status"] == "COMPLETED"
    assert result["trigger_cal_idx"] == 120
    assert result["entry_cal_idx"] == 122
    assert result["exit_cal_idx"] == 242
    assert result["exit_reason"] == "H120_NEXT_LEGAL_OPEN"


def test_five_failure_closes_exit_only_at_next_legal_open():
    rows = [row(idx) for idx in range(101, 122)]
    rows.extend(row(idx, close=9.0, open_=9.5) for idx in range(122, 127))
    rows.append(row(127, close=9.0, open_=8.5, down=8.0))
    result = strategy.replay_one(candidate(), pd.DataFrame(rows))
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 121
    assert result["failure_signal_cal_idx"] == 126
    assert result["exit_cal_idx"] == 127
    assert result["exit_reason"] == "LOSS_OF_ACCEPTANCE_NEXT_LEGAL_OPEN"


def test_coordinate_lineage_drift_fails_closed_before_entry():
    rows = [row(idx) for idx in range(101, 121)]
    rows.append(row(121, lineage=3.0))
    result = strategy.replay_one(candidate(), pd.DataFrame(rows))
    assert result["status"] == "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY"


def test_development_date_cap_is_pre_2021():
    assert strategy.MAXIMUM_DATE == pd.Timestamp("2020-12-31")

