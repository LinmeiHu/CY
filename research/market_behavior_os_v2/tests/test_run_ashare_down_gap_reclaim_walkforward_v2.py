from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/run_ashare_down_gap_reclaim_walkforward_v2.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("down_gap_reclaim_walkforward_v2_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _event(
    entry_id: str,
    symbol: str,
    signal_day: str,
    *,
    gap: float = 0.10,
    exit_shift: int = 2,
) -> dict:
    day = pd.Timestamp(signal_day)
    dates = [day + pd.offsets.BDay(i) for i in range(4)]
    return {
        "entry_id": entry_id,
        "symbol": symbol,
        "board": "Main Board",
        "sleeve": "MAIN",
        "bar_end_time": day + pd.Timedelta(hours=10),
        "reclaim_date": day,
        "entry_price": 10.0,
        "close": 10.0,
        "gap_pct": gap,
        "gap_age_trading_days": 2,
        "dryup_3_20": 0.4,
        "compression_trend": 0.4,
        "breadth": 0.1,
        "is_st": False,
        "t1_date": dates[1],
        "t2_date": dates[exit_shift],
        "t3_date": dates[3],
        "next_legal_open_date": dates[1],
        "t1_legal_open_price": 10.0,
        "t1_close_price": 10.0,
        "t2_close_price": 10.0,
        "t3_close_price": 10.0,
    }


def _calendar() -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-02", periods=6)


def _params(module, *, k=2, exit_code=2):
    return module.Params(0.05, -1, -1.0, -1.0, 0, exit_code, k, 0)


def _search_row(module, key: str, calmar: float, sleeve: str = "MAIN") -> dict:
    params = module.Params(0.05, -1, -1.0, -1.0, 0, 0, 20, 0)
    return {
        "sleeve": sleeve,
        "parameter_key": key,
        **module.asdict(params),
        "active_filters": 0,
        "trade_count": 100,
        "recent_year_trade_count": 20,
        "calmar": calmar,
        "sharpe": 1.0,
        "median_year_return": 0.1,
        "cagr": 0.1,
        "top5_day_contribution": 0.2,
    }


def test_folds_never_include_test_year_in_training():
    module = _module()
    assert all(train_end == test_year - 1 for _, train_end, test_year in module.FOLDS)
    assert module.TEST_YEARS == tuple(range(2017, 2022))


def test_parameter_grid_is_exactly_frozen_size():
    module = _module()
    assert len(module.GRID) == 8748
    assert len({params.key for params in module.GRID}) == 8748


def test_board_breadth_thresholds_are_training_only_and_independent():
    module = _module()
    breadth = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2016-01-01", "2016-01-02", "2017-01-01"] * 2),
            "sleeve": ["MAIN"] * 3 + ["CHINEXT"] * 3,
            "breadth": [0.01, 0.03, 0.99, 0.20, 0.40, 0.00],
        }
    )
    main = module.breadth_thresholds(breadth, "MAIN", 2016)
    chi = module.breadth_thresholds(breadth, "CHINEXT", 2016)
    assert main == (0.025, 0.028)
    assert np.allclose(chi, (0.35, 0.38))


def test_deterministic_champion_selection_uses_lexical_last_tie_break():
    module = _module()
    frame = pd.DataFrame([_search_row(module, "z", 1.0), _search_row(module, "a", 1.0)])
    assert module.select_top10(frame).iloc[0].parameter_key == "a"


def test_main_and_chinext_candidate_selection_remains_separate():
    module = _module()
    frame = pd.DataFrame(
        [
            _search_row(module, "main", 2.0, "MAIN"),
            _search_row(module, "chi", 3.0, "CHINEXT"),
        ]
    )
    assert module.select_top10(frame.loc[frame.sleeve.eq("MAIN")]).iloc[0].parameter_key == "main"
    assert module.select_top10(frame.loc[frame.sleeve.eq("CHINEXT")]).iloc[0].parameter_key == "chi"


def test_position_cap_no_leverage_and_same_symbol_skip():
    module = _module()
    events = pd.DataFrame(
        [
            _event("a0", "A", "2020-01-02", gap=0.12),
            _event("b0", "B", "2020-01-02", gap=0.11),
            _event("c0", "C", "2020-01-02", gap=0.10),
            _event("a1", "A", "2020-01-03", gap=0.15),
        ]
    )
    _, trades, metrics = module.simulate_detailed(
        events,
        _calendar(),
        _params(module),
        pd.Timestamp("2020-01-02"),
        pd.Timestamp("2020-01-09"),
        0.0,
        0.0,
    )
    assert metrics["maximum_concurrent_positions"] == 2
    assert metrics["max_concurrent_positions_violation_count"] == 0
    assert metrics["negative_cash_or_leverage_violation_count"] == 0
    assert metrics["duplicate_position_entry_count"] == 0
    assert trades.symbol.value_counts().max() == 1


def test_entry_and_exit_costs_are_both_applied():
    module = _module()
    events = pd.DataFrame([_event("a0", "A", "2020-01-02")])
    _, trades, _ = module.simulate_detailed(
        events,
        _calendar(),
        _params(module, k=1),
        pd.Timestamp("2020-01-02"),
        pd.Timestamp("2020-01-09"),
        0.0,
        0.0,
    )
    expected = (1 - module.EXIT_COST) / (1 + module.ENTRY_COST) - 1
    assert np.isclose(trades.iloc[0].net_return, expected)


def test_year_boundary_censors_unrealized_exit():
    module = _module()
    events = pd.DataFrame([_event("a0", "A", "2020-01-02")])
    nav, trades, metrics = module.simulate_detailed(
        events,
        _calendar(),
        _params(module, k=1),
        pd.Timestamp("2020-01-02"),
        pd.Timestamp("2020-01-03"),
        0.0,
        0.0,
    )
    assert trades.empty
    assert metrics["trade_count"] == 0
    assert nav.nav.eq(1.0).all()


def test_fixed_combined_sleeve_has_no_cross_sleeve_capital_transfer():
    module = _module()
    dates = pd.bdate_range("2020-01-02", periods=2)
    main = pd.DataFrame({"trade_date": dates, "nav": [1.0, 2.0]})
    chi = pd.DataFrame({"trade_date": dates, "nav": [1.0, 1.0]})
    combined = module.combine_fixed_sleeves(main, chi)
    assert combined.nav.tolist() == [1.0, 1.5]
    assert combined.main_nav.tolist() == [1.0, 2.0]
    assert combined.chinext_nav.tolist() == [1.0, 1.0]


def test_optimized_summary_matches_transparent_ledger():
    module = _module()
    calendar = _calendar()
    events = pd.DataFrame(
        [
            _event("a0", "A", "2020-01-02", gap=0.12),
            _event("b0", "B", "2020-01-02", gap=0.11),
        ]
    ).sort_values(["bar_end_time", "symbol"])
    day_map = pd.Series(np.arange(len(calendar), dtype=np.int32), index=calendar)
    events["entry_day"] = events.reclaim_date.map(day_map).astype(np.int32)
    events["exit_day_0"] = events.next_legal_open_date.map(day_map).astype(np.int32)
    events["exit_day_1"] = events.t1_date.map(day_map).astype(np.int32)
    events["exit_day_2"] = events.t2_date.map(day_map).astype(np.int32)
    events["exit_day_3"] = events.t3_date.map(day_map).astype(np.int32)
    events["symbol_id"] = pd.factorize(events.symbol, sort=True)[0].astype(np.int32)
    params = _params(module)
    summary = module.run_summary(
        module.event_arrays(events), calendar, params, calendar[0], calendar[-1], 0.0, 0.0
    )
    _, _, detailed = module.simulate_detailed(
        events, calendar, params, calendar[0], calendar[-1], 0.0, 0.0
    )
    for key in (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe",
        "trade_count",
        "win_rate",
        "average_trade_return",
    ):
        assert np.isclose(summary[key], detailed[key])


def test_frozen_spec_keeps_validation_and_final_oos_sealed():
    module = _module()
    spec = module.json.loads(module.SPEC.read_text(encoding="utf-8"))
    assert spec["sealed"]["validation_opened"] is False
    assert spec["sealed"]["final_oos_opened"] is False
    assert spec["development"] == ["2014-01-01", "2021-12-31"]
