import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_annual_amihud_illiquidity_compensation_mother_v1_stage_b.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("amihud_stage_b",SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
stage_b = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(stage_b)


def candidate(**overrides):
    values = {
        "event_id": "000001.SZ|20141231","symbol": "000001.SZ",
        "sleeve": "MAIN","causal_industry": "TEST","portfolio_year": 2015,
        "formation_year": 2014,"valid_daily_observations": 240,
        "annual_amihud": 1e-9,"signal_date": pd.Timestamp("2014-12-31"),
        "signal_cal_idx": 100,"market_regime": "TRANSITION",
        "market_median_ret20": 0.0,"market_median_ret60": 0.0,
        "invalid_step_cum": 2.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def row(cal_idx,*,open_=10.0,up=11.0,down=9.0,lineage=2.0,tradable=True):
    date = pd.Timestamp("2014-12-31") + pd.offsets.BDay(cal_idx-100)
    return {
        "trade_date": date,"cal_idx": cal_idx,"open": open_,"coord_open": open_,
        "invalid_step_cum": lineage,"coordinate_factor": 1.0,
        "trade_status": int(tradable),"current_day_data_tradable": tradable,
        "current_valid": tradable,"history_valid": True,"market_rule_valid": True,
        "corporate_action_count": 0,"corporate_action_valid": True,
        "corporate_action_blocking": False,"hard_valid": True,
        "up_limit_price": up,"down_limit_price": down,
    }


def test_entry_is_next_legal_non_limit_up_open():
    path = pd.DataFrame([row(101,open_=11,up=11),row(102),row(222,open_=12)])
    result = stage_b.replay_one(candidate(),path)
    assert result["status"] == "COMPLETED"
    assert result["entry_cal_idx"] == 102
    assert result["exit_cal_idx"] == 222


def test_h120_waits_for_sellable_open():
    path = pd.DataFrame([
        row(101),row(221,open_=9,down=9),row(222,open_=9.5,down=9)
    ])
    result = stage_b.replay_one(candidate(),path)
    assert result["status"] == "COMPLETED"
    assert result["exit_cal_idx"] == 222
    assert result["net_return"] == 9.5/10-1-0.004


def test_entry_window_is_not_extended_after_three_sessions():
    path = pd.DataFrame([
        row(101,tradable=False),row(102,open_=11,up=11),
        row(103,tradable=False),row(104),row(224),
    ])
    assert stage_b.replay_one(candidate(),path)["status"] == "NO_LEGAL_ENTRY"


def test_coordinate_lineage_change_fails_closed():
    path = pd.DataFrame([row(101),row(221,lineage=3.0)])
    result = stage_b.replay_one(candidate(),path)
    assert result["status"] == "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY"


def test_frozen_annual_measure_is_absolute_return_per_amount():
    stage_a_script = SCRIPT.with_name(
        "run_ashare_annual_amihud_illiquidity_compensation_mother_v1_stage_a.py"
    )
    spec = importlib.util.spec_from_file_location("amihud_stage_a",stage_a_script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.annual_measure_sql() == "avg(abs(step_return) / amount)"
