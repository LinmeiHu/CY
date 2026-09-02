from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_former_leader_formation_panic_v5.py"


@lru_cache(maxsize=1)
def _module():
    spec = importlib.util.spec_from_file_location("formation_panic_v5_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_formation_breadth_is_gap_date_opening_state_and_reclaim_state_is_diagnostic_only():
    v5 = _module()
    events, _, breadth, audit = v5.load_events()
    expected = breadth.assign(expected=breadth.gap_count / breadth.universe_size)
    assert np.allclose(expected.breadth, expected.expected)
    joined = events.merge(
        breadth[["trade_date", "sleeve", "breadth"]],
        left_on=["gap_date", "sleeve"], right_on=["trade_date", "sleeve"],
        how="left", validate="many_to_one",
    )
    assert np.allclose(joined.formation_down_gap_breadth, joined.breadth)
    assert audit["formation_panic_date_mismatch_count"] == 0
    group = events.head(2).copy()
    group["reclaim_date_down_gap_breadth"] = [0.0, 1.0]
    params = replace(v5.BASELINE, panic_code=1)
    mask1 = v5.event_eligibility_mask(group, params, 0.0, "t1_date", "t1_close_price", pd.Timestamp("2021-12-31"), set())
    group["reclaim_date_down_gap_breadth"] = [1.0, 0.0]
    mask2 = v5.event_eligibility_mask(group, params, 0.0, "t1_date", "t1_close_price", pd.Timestamp("2021-12-31"), set())
    assert mask1.equals(mask2)


def test_panic_quantiles_are_train_only_and_board_specific():
    v5 = _module()
    events, _, _, _ = v5.load_events()
    main = v5.calibrate_panic(events, "MAIN", 2016)
    chinext = v5.calibrate_panic(events, "CHINEXT", 2016)
    assert main["last_date"].year <= 2016
    assert chinext["last_date"].year <= 2016
    assert main["q75"] != chinext["q75"]
    changed = events.copy()
    changed.loc[changed.gap_date.dt.year == 2017, "formation_down_gap_breadth"] = 999.0
    assert v5.calibrate_panic(changed, "MAIN", 2016)["q90"] == main["q90"]


def test_counterfactuals_change_only_authorized_dimensions():
    v5 = _module()
    champion = v5.Params(.95, .8, .4, .09, 3, 2, 2, 50)
    no_panic = replace(champion, panic_code=0)
    assert {key: value for key, value in champion.__dict__.items() if key != "panic_code"} == {
        key: value for key, value in no_panic.__dict__.items() if key != "panic_code"
    }
    broad = replace(v5.BROAD, panic_code=champion.panic_code, exit_code=champion.exit_code, k=champion.k)
    assert (broad.panic_code, broad.exit_code, broad.k) == (champion.panic_code, champion.exit_code, champion.k)
    assert (broad.leader_min, broad.runup_min, broad.drawdown_min, broad.gap_min, broad.age_max) == (.9, .5, .3, .07, -1)


def test_strict_gap_uniqueness_costs_k_cash_and_year_boundary():
    v5 = _module()
    events, calendar, _, audit = v5.load_events()
    assert audit["gap_ids_with_more_than_one_first_reclaim"] == 0
    assert audit["strict_gap_condition_violation_count"] == 0
    assert audit["trigger_outside_strict_gap_admitted_count"] == 0
    assert events.reclaim_date.max() <= pd.Timestamp("2021-12-31")
    calibration = v5.calibrate_panic(events, "MAIN", 2016)
    nav, trades, metrics = v5.replay_year(events.loc[events.sleeve.eq("MAIN")], calendar, v5.BASELINE, calibration, 2017)
    assert metrics["maximum_concurrent_positions"] <= v5.BASELINE.k
    assert metrics["duplicate_position_entry_count"] == 0
    assert metrics["max_concurrent_positions_violation_count"] == 0
    assert metrics["negative_cash_or_leverage_violation_count"] == 0
    assert nav.cash.min() >= -1e-12
    assert trades.exit_date.max() <= calendar[calendar.year == 2017][-1]
    expected = trades.exit_price * (1 - v5.EXIT_COST) / (trades.entry_price * (1 + v5.ENTRY_COST)) - 1
    assert np.allclose(trades.net_return, expected)


def test_numba_search_and_detailed_replay_are_equivalent():
    v5 = _module()
    events, calendar, _, _ = v5.load_events()
    calibration = v5.calibrate_panic(events, "MAIN", 2016)
    params = v5.Params(.95, .8, .3, .09, -1, 0, 0, 50)
    board = events.loc[events.sleeve.eq("MAIN")]
    start = calendar[calendar.year == 2014][0]
    end = calendar[calendar.year == 2016][-1]
    summary = v5.run_summary(v5.event_arrays(board), calendar, params, calibration, start, end)
    _, _, detailed = v5.simulate_detailed(board, calendar, params, calibration, start, end)
    for key in ("total_return", "cagr", "max_drawdown", "sharpe", "calmar"):
        assert np.isclose(summary[key], detailed[key], atol=1e-12)
    assert summary["trade_count"] == detailed["trade_count"]
