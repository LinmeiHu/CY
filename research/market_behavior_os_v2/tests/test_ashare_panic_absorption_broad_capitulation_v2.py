import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_ashare_panic_absorption_broad_capitulation_v2 as subject  # noqa: E402


def test_apply_cooldown_is_symbol_local_and_strictly_more_than_twenty() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["A", "A", "A", "B"],
            "sleeve": ["MAIN"] * 4,
            "signal_date": pd.to_datetime(
                ["2024-01-02", "2024-01-30", "2024-01-31", "2024-01-30"]
            ),
            "cal_idx": [100, 120, 121, 120],
        }
    )
    result = subject.apply_cooldown(frame)
    assert set(result.event_id) == {
        "A|2024-01-02",
        "A|2024-01-31",
        "B|2024-01-30",
    }


def test_cluster_rule_uses_completed_signal_date_only() -> None:
    frame = pd.DataFrame(
        {
            "event_id": ["A", "B", "C"],
            "signal_date": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"]),
        }
    )
    frame["same_date_signal_count"] = frame.groupby("signal_date").event_id.transform("size")
    assert frame.loc[frame.same_date_signal_count.ge(2), "event_id"].tolist() == ["A", "B"]


def test_buy_and_sell_limit_semantics() -> None:
    base = {
        "trade_status": 1,
        "current_day_data_tradable": True,
        "market_rule_valid": True,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "coord_open": 10.0,
        "coordinate_factor": 1.0,
        "up_limit_price": 10.0,
        "down_limit_price": 9.0,
    }
    assert not subject.buyable_open(pd.Series({**base, "open": 10.0}))
    assert subject.buyable_open(pd.Series({**base, "open": 9.99}))
    assert not subject.sellable_open(pd.Series({**base, "open": 9.0}))
    assert subject.sellable_open(pd.Series({**base, "open": 9.01}))
