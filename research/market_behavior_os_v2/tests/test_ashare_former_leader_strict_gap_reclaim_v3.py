from __future__ import annotations

import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_former_leader_strict_gap_reclaim_v3.py"
)


@lru_cache(maxsize=1)
def _module():
    spec = importlib.util.spec_from_file_location(
        "former_leader_strict_gap_reclaim_v3_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _features() -> pd.DataFrame:
    module = _module()
    frame = pd.read_parquet(module.FEATURES_EXTERNAL)
    for column in ("gap_date", "reclaim_date", "bar_end_time", "peak_date", "pregap_date"):
        frame[column] = pd.to_datetime(frame[column])
    for column in ("v3_final_candidate", "strict_gap_condition", "trigger_inside_strict_gap"):
        frame[column] = frame[column].astype("boolean").fillna(False).astype(bool)
    return frame


@lru_cache(maxsize=1)
def _result() -> dict:
    module = _module()
    return json.loads(module.RESULT.read_text(encoding="utf-8"))


def _event(entry_id: str, symbol: str, signal_day: str, *, gap_id: str | None = None) -> dict:
    day = pd.Timestamp(signal_day)
    dates = [day + pd.offsets.BDay(i) for i in range(4)]
    return {
        "entry_id": entry_id,
        "gap_id": gap_id or entry_id,
        "symbol": symbol,
        "is_st": False,
        "bar_end_time": day + pd.Timedelta(hours=10),
        "reclaim_date": day,
        "entry_price": 10.0,
        "trigger_close": 10.0,
        "breadth": 0.1,
        "leader_percentile": 0.99,
        "prior_runup": 1.0,
        "deep_drawdown": 0.5,
        "strict_gap_width_pct": 0.1,
        "gap_pct": 0.1,
        "gap_age_trading_days": 0,
        "post_gap_dryup": np.nan,
        "intraday_dryup": 0.4,
        "compression_trend": 0.4,
        "next_legal_open_date": dates[1],
        "t1_date": dates[1],
        "t2_date": dates[2],
        "t3_date": dates[3],
        "t1_legal_open_price": 10.0,
        "t1_close_price": 10.0,
        "t2_close_price": 10.0,
        "t3_close_price": 10.0,
    }


def _calendar() -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-02", periods=6)


def _params(module, *, k: int = 2):
    return module.Params(0.90, 0.50, 0.30, 0.05, -1, -1.0, -1.0, 0, k, 0)


def test_former_leader_peak_is_strictly_pre_gap():
    frame = _features()
    assert frame.peak_date.lt(frame.gap_date).all()


def test_runup_uses_only_history_ending_at_peak():
    frame = _features()
    valid = frame.prior_runup.notna()
    assert frame.loc[valid, "peak_date"].lt(frame.loc[valid, "gap_date"]).all()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "lag(adjusted_close,60) OVER w AS adjusted_close_lag60" in source
    assert "adjusted_close/adjusted_close_lag60-1 AS ret60" in source
    assert "pk.cal_idx BETWEEN p.gap_cal_idx-120 AND p.gap_cal_idx-1" in source


def test_leadership_percentile_is_same_board_pit_rank():
    frame = _features().loc[lambda x: x.leader_percentile.notna()]
    assert frame.leader_percentile.between(0, 1).all()
    assert frame.leader_universe_size.ge(2).all()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "PARTITION BY trade_date,sleeve ORDER BY ret60" in source
    assert "source_notice_date<=s.trade_date" in source


def test_deep_drawdown_uses_comparable_pregap_price():
    frame = _features()
    expected = 1 - frame.pregap_adjusted_close / frame.peak_price_adjusted
    assert np.allclose(frame.deep_drawdown, expected, equal_nan=True)
    assert frame.pregap_date.lt(frame.gap_date).all()


def test_strict_gap_requires_open_below_previous_low():
    admitted = _features().loc[lambda x: x.v3_final_candidate]
    assert admitted.gap_open.lt(admitted.prev_low_daily).all()


def test_trigger_must_remain_inside_strict_gap():
    admitted = _features().loc[lambda x: x.v3_final_candidate]
    assert admitted.trigger_price.le(admitted.prev_low_daily + 1e-10).all()


def test_one_signal_maximum_per_gap_id():
    admitted = _features().loc[lambda x: x.v3_final_candidate]
    assert not admitted.gap_id.duplicated().any()
    assert _result()["audit"]["gap_ids_with_more_than_one_first_reclaim"] == 0


def test_postgap_dryup_cannot_use_pregap_numerator_sessions():
    frame = _features()
    same_day = frame.reclaim_date.eq(frame.gap_date)
    assert frame.loc[same_day, "post_gap_session_count"].fillna(0).eq(0).all()
    assert (
        frame.loc[~same_day & frame.post_gap_session_count.notna(), "post_gap_session_count"]
        .between(1, 3)
        .all()
    )


def test_postgap_dryup_cannot_use_post_trigger_sessions():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "d.trade_date>p.gap_date AND d.trade_date<p.reclaim_date" in source
    assert _result()["audit"]["post_trigger_volume_used_in_dryup_count"] == 0


def test_intraday_dryup_cannot_use_crossing_or_postcross_volume():
    result = _result()
    assert result["audit"]["future_volume_leakage_count"] == 0
    assert (
        result["input_audit"]["inherited_v1_invariants"]["post_trigger_volume_used_in_dryup_count"]
        == 0
    )


def test_main_and_chinext_selectors_are_independent():
    result = _result()
    main = result["sleeves"]["MAIN"]["selections"]
    chi = result["sleeves"]["CHINEXT"]["selections"]
    assert all(row["sleeve"] == "MAIN" for row in main)
    assert all(row["sleeve"] == "CHINEXT" for row in chi)
    assert result["audit"]["cross_board_parameter_contamination_count"] == 0


def test_test_year_cannot_select_itself():
    result = _result()
    rows = result["sleeves"]["MAIN"]["selections"] + result["sleeves"]["CHINEXT"]["selections"]
    assert all(row["train_end"] == row["test_year"] - 1 for row in rows)
    assert result["audit"]["test_year_used_in_own_parameter_selection_count"] == 0


def test_position_k_cap():
    module = _module()
    events = pd.DataFrame([_event(f"e{i}", f"S{i}", "2020-01-02") for i in range(4)])
    _, _, metrics = module.simulate_detailed(
        events, _calendar(), _params(module, k=2), _calendar()[0], _calendar()[-1]
    )
    assert metrics["maximum_concurrent_positions"] == 2
    assert metrics["max_concurrent_positions_violation_count"] == 0


def test_no_duplicate_stock_position():
    module = _module()
    events = pd.DataFrame([_event("a", "SAME", "2020-01-02"), _event("b", "SAME", "2020-01-02")])
    _, trades, metrics = module.simulate_detailed(
        events, _calendar(), _params(module), _calendar()[0], _calendar()[-1]
    )
    assert metrics["duplicate_position_entry_count"] == 0
    assert trades.symbol.value_counts().max() == 1


def test_no_negative_cash_or_leverage():
    module = _module()
    events = pd.DataFrame([_event(f"e{i}", f"S{i}", "2020-01-02") for i in range(4)])
    nav, _, metrics = module.simulate_detailed(
        events, _calendar(), _params(module, k=2), _calendar()[0], _calendar()[-1]
    )
    assert metrics["negative_cash_or_leverage_violation_count"] == 0
    assert nav.cash.ge(-1e-12).all()


def test_forty_basis_point_round_trip_cost_is_applied():
    module = _module()
    events = pd.DataFrame([_event("a", "S", "2020-01-02")])
    _, trades, _ = module.simulate_detailed(
        events, _calendar(), _params(module, k=1), _calendar()[0], _calendar()[-1]
    )
    expected = (1 - module.EXIT_COST) / (1 + module.ENTRY_COST) - 1
    assert np.isclose(trades.iloc[0].net_return, expected)
    assert module.ENTRY_COST == module.EXIT_COST == 0.002
