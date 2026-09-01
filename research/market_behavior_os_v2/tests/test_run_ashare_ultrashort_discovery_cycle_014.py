from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "research/market_behavior_os_v2/scripts/run_ashare_ultrashort_discovery_cycle_014.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("cycle014_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _path_rows(opens: list[float], lows: list[float]) -> pd.DataFrame:
    rows = []
    for offset, (open_price, low_price) in enumerate(zip(opens, lows, strict=True), start=1):
        rows.append(
            {
                "offset": offset,
                "trade_date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=offset),
                "open": open_price,
                "low": low_price,
                "amount": 100_000_000.0,
                "hard_valid": True,
                "trade_status": 1,
                "current_day_data_tradable": True,
                "buy_blocked_open": False,
                "sell_blocked_open": False,
                "corporate_action_count": 0,
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_available_date": pd.NaT,
                "share_multiplier": 1.0,
                "cash_per_share": 0.0,
                "rights_ratio": 0.0,
                "available_at": pd.Timestamp("2020-01-01") + pd.Timedelta(days=offset),
            }
        )
    return pd.DataFrame(rows)


def test_frozen_gate_audit_and_family_map_load():
    module = _module()
    spec = module._load_spec()
    assert list(spec["families"]) == list(module.FAMILIES)
    assert [row["classification"] for row in spec["deduplication"][:5]] == [
        "NEW_DISTINCT",
        "NEW_DISTINCT",
        "NEIGHBOR_OF_PRIOR",
        "NEIGHBOR_OF_PRIOR",
        "DEFERRED",
    ]


def test_natural_horizons_do_not_require_longer_path():
    module = _module()
    rows = _path_rows([10.0, 10.5], [9.8, 10.2])
    h1 = module._one_outcome(rows, 1)
    h2 = module._one_outcome(rows, 2)
    assert h1["status_h1"] == "COMPLETE"
    assert h2["status_h2"] == "INCOMPLETE"


def test_cost_and_severe_loss_use_natural_path():
    module = _module()
    rows = _path_rows([10.0, 9.5, 10.2], [8.8, 9.4, 10.0])
    outcome = module._one_outcome(rows, 2)
    assert outcome["status_h2"] == "COMPLETE"
    assert outcome["net_return_h2"] < 0.02
    assert outcome["severe_loss10_h2"] is True


def test_entry_and_exit_limits_fail_closed():
    module = _module()
    rows = _path_rows([10.0, 10.1], [9.9, 10.0])
    rows.loc[0, "buy_blocked_open"] = True
    assert module._one_outcome(rows, 1)["status_h1"] == "ENTRY_NOT_EXECUTABLE"
    rows.loc[0, "buy_blocked_open"] = False
    rows.loc[1, "sell_blocked_open"] = True
    assert module._one_outcome(rows, 1)["status_h1"] == "EXIT_NOT_EXECUTABLE"


def test_limit_coordinate_uses_exact_cent_ticks():
    module = _module()
    ticks = module._cent_ticks(np.array([7.769999980926514, 7.76, 7.755]))
    assert ticks.tolist() == [777, 776, 776]


def test_replay_plan_is_next_open_and_t_plus_two_exit():
    module = _module()
    calendar = [pd.Timestamp(f"2020-01-0{day}").date() for day in range(1, 6)]
    panel = pd.DataFrame(
        [
            {
                "family": module.FAMILIES[0],
                "leg": "selected",
                "signal_rank": 1,
                "status_h2": "COMPLETE",
                "trade_date": calendar[0],
                "symbol": "000001.SZ",
                "industry": "bank",
            }
        ]
    )
    plan = module._replay_plans(panel, module.FAMILIES[0], "selected", calendar, "test")
    assert plan.iloc[0].entry_index == 1
    assert plan.iloc[0].due_index == 3


def test_matched_control_severe_loss_is_date_matched():
    module = _module()
    rows = []
    dates = [pd.Timestamp("2020-01-02"), pd.Timestamp("2021-01-04")]
    for family in module.FAMILIES:
        for trade_date in dates:
            for leg, severe, net in (("selected", True, 0.01), ("control", False, 0.0)):
                row = {
                    "family": family,
                    "leg": leg,
                    "trade_date": trade_date,
                    "symbol": f"{family[:3]}-{leg}-{trade_date.year}",
                    "industry": "x",
                }
                for horizon in (1, 2, 3):
                    row[f"status_h{horizon}"] = "COMPLETE"
                    row[f"net_return_h{horizon}"] = net
                    row[f"severe_loss10_h{horizon}"] = severe
                    row[f"adverse_return_h{horizon}"] = -0.11 if severe else -0.01
                rows.append(row)
    summary = module._summarize(pd.DataFrame(rows))
    selected = summary.loc[
        summary.family.eq(module.FAMILIES[0])
        & summary.leg.eq("selected")
        & summary.period.eq("full")
        & summary.horizon.eq(2)
    ].iloc[0]
    assert selected.mean_excess_vs_control == 0.01
    assert selected.severe_loss10_disadvantage == 1.0
