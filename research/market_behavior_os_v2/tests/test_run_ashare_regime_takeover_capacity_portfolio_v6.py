from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "run_ashare_regime_takeover_capacity_portfolio_v6.py"
SPEC = importlib.util.spec_from_file_location("capacity_takeover_v6_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
V6 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V6
SPEC.loader.exec_module(V6)


def _selected() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "symbol": ["a", "b", "c", "d"],
            "signal_date": pd.to_datetime(
                ["2020-01-01", "2020-01-01", "2020-01-02", "2020-01-04"]
            ),
            "diversified_rank": [1, 2, 1, 1],
            "market_route": ["BULL_TREND"] * 4,
        }
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "status": ["COMPLETED"] * 4,
            "entry_date": pd.to_datetime(
                ["2020-01-02", "2020-01-02", "2020-01-03", "2020-01-04"]
            ),
            "entry_cal_idx": [1, 1, 2, 3],
            "exit_date": pd.to_datetime(
                ["2020-01-03", "2020-01-05", "2020-01-06", "2020-01-07"]
            ),
            "exit_cal_idx": [2, 4, 5, 6],
            "exit_reason": ["TARGET_10"] * 4,
            "holding_sessions": [1, 3, 3, 3],
            "gross_return": [0.10] * 4,
            "net_return": [0.096] * 4,
        }
    )


def test_capacity_does_not_reuse_same_day_exit_slot() -> None:
    result = V6.admit_capacity(
        _selected(), _outcomes(), max_names_per_event=2, max_concurrent=2
    ).set_index("event_id")
    assert result.loc["a", "capacity_status"] == "ADMITTED"
    assert result.loc["b", "capacity_status"] == "ADMITTED"
    assert result.loc["c", "capacity_status"] == "CAPACITY_REJECTED"
    # Position a exits on Jan 3, so its slot becomes reusable only after Jan 3.
    assert result.loc["d", "capacity_status"] == "ADMITTED"


def test_cash_ledger_conserves_cash_plus_open_cost_basis(monkeypatch) -> None:
    monkeypatch.setattr(V6, "SLOT_WEIGHT", 0.5)
    capacity = V6.admit_capacity(
        _selected().iloc[:2], _outcomes().iloc[:2], max_names_per_event=2, max_concurrent=2
    )
    ledger, summary = V6.cash_ledger(capacity, [2020])
    assert summary["cash_plus_open_cost_basis_conserved"] is True
    assert summary["ending_nav_at_open_cost"] == 1.096
    assert summary["unresolved_positions_at_end"] == 0
    assert ledger.iloc[0].cash == 0.0
    assert ledger.iloc[0].open_cost_basis == 1.0
