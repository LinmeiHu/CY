from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_industry_consensus_q1_overextension_veto_v1.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("overextension_veto_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_event_feature_uses_signal_date_pit_members_only() -> None:
    module = _module()
    signal = date(2020, 1, 3)
    corrected = pd.DataFrame(
        {
            "trade_date": pd.to_datetime([signal, signal, signal]),
            "industry": ["A", "A", "B"],
            "r20": [0.0, 0.18, 1.0],
        }
    )
    plans = pd.DataFrame(
        {
            "signal_date": [signal, signal],
            "industry": ["A", "A"],
        }
    )
    features = module._event_features(corrected, plans)
    expected = ((pd.Series([0.0, 0.18])).map(module.np.expm1)).mean()
    assert len(features) == 1
    assert abs(features.industry_prior20_member_mean.iloc[0] - expected) < 1e-12
    assert bool(features.admitted.iloc[0]) is True


def test_trade_plan_mapping_preserves_due_and_forced_lots() -> None:
    module = _module()
    calendar = [date(2020, 1, 1) + timedelta(days=index) for index in range(20)]
    plans = pd.DataFrame(
        {
            "signal_date": [calendar[0], calendar[1]],
            "symbol": ["X", "Y"],
            "industry": ["A", "B"],
            "entry_index": [1, 2],
            "due_index": [5, 10],
        }
    )
    trades = pd.DataFrame(
        {
            "symbol": ["X", "Y"],
            "industry": ["A", "B"],
            "exit_date": [calendar[5], calendar[6]],
            "exit_reason": ["DUE", "FORCED"],
            "invested_cost": [100.0, 100.0],
            "net_return": [0.1, -0.1],
        }
    )
    mapped = module._attach_plans_to_trades(trades, plans, calendar)
    assert mapped.plan_id.nunique() == 2
    assert set(mapped.signal_date) == {calendar[0], calendar[1]}


def test_screen_requires_every_frozen_block_gate() -> None:
    module = _module()
    early_dates = [date(2019, 1, 1) + timedelta(days=index) for index in range(20)]
    late_dates = [date(2022, 1, 1) + timedelta(days=index) for index in range(20)]
    events = pd.DataFrame(
        {
            "signal_date": early_dates + late_dates + [date(2019, 3, 1), date(2022, 3, 1)],
            "industry": ["A"] * 42,
            "industry_prior20_member_mean": [0.05] * 40 + [0.20, 0.20],
            "admitted": [True] * 40 + [False, False],
            "block": ["2018-2020"] * 20 + ["2021-2023"] * 20 + ["2018-2020", "2021-2023"],
        }
    )
    trades = pd.DataFrame(
        {
            "signal_date": events.signal_date,
            "industry": events.industry,
            "net_return": [0.02] * 40 + [-0.02, -0.02],
        }
    )
    _, gate = module._screen(trades, events)
    assert gate["passed"] is True
