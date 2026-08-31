from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_indep_funnel_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("ashare_indep_funnel", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def _path(*, buy_blocked: bool = False, action: bool = False) -> pd.DataFrame:
    rows = []
    for horizon in range(1, 21):
        trade_date = pd.Timestamp("2020-01-02") + pd.offsets.BDay(horizon - 1)
        rows.append(
            {
                "candidate_row": 0,
                "horizon": horizon,
                "trade_date": trade_date,
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 10.0 if not action or horizon < 3 else 5.0,
                "low": 10.0 if not action or horizon < 3 else 5.0,
                "close": 10.0 if not action or horizon < 3 else 5.0,
                "amount": 100_000_000.0,
                "hard_valid": True,
                "trade_status": 1,
                "current_day_data_tradable": True,
                "buy_blocked_open": buy_blocked and horizon == 1,
                "sell_blocked_open": False,
                "corporate_action_count": 1 if action and horizon == 3 else 0,
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_available_date": trade_date
                if action and horizon == 3
                else pd.NaT,
                "share_multiplier": 2.0 if action and horizon == 3 else 1.0,
                "cash_per_share": 0.0,
                "rights_ratio": 0.0,
                "available_at": trade_date + pd.Timedelta(hours=15),
            }
        )
    return pd.DataFrame(rows)


def test_frozen_spec_and_family_order() -> None:
    spec = MODULE._load_spec()
    assert spec["research_window"]["end"] == "2023-12-29"
    assert len(spec["families"]) == 7
    assert spec["promotion"]["maximum_families"] == 3


def test_screen_outcome_applies_visible_action_without_same_bar_fill() -> None:
    result = MODULE._screen_outcome(_path(action=True))
    assert result["entry_status"] == "EXECUTABLE"
    assert result["status_h5"] == "COMPLETE"
    assert math.isclose(result["gross_return_h5"], 0.0, abs_tol=1e-12)
    assert result["net_return_h5"] < 0.0


def test_screen_outcome_fails_closed_on_blocked_next_open() -> None:
    result = MODULE._screen_outcome(_path(buy_blocked=True))
    assert result["entry_status"] == "NEXT_OPEN_NOT_EXECUTABLE"
    assert result["status_h5"] == "INCOMPLETE"
