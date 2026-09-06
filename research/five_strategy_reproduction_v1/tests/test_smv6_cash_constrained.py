import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT = Path(__file__).parents[1] / "replay_smv6_cash_constrained.py"
spec = importlib.util.spec_from_file_location("cash_replay", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def platform(cash=100_000):
    day = date(2020, 1, 2)
    symbols = ["A.SH", "B.SH", "C.SH"]
    daily = {
        s: pd.DataFrame(
            {"pre_adj_close": [10.0], "volume_raw": [1_000.0], "amount_cny": [10_000.0]},
            index=pd.to_datetime([day]),
        )
        for s in symbols
    }
    minute = {
        s: pd.DataFrame(
            {
                "trade_date": [day, day],
                "bar_role": ["OPEN_BAR_09_30", "FINAL_CLOSE_BAR"],
                "pre_adj_close": [10.0, 10.0],
                "pre_adj_open": [10.0, 10.0],
            }
        )
        for s in symbols
    }
    availability = pd.DataFrame(
        [
            {
                "trade_date": day,
                "symbol": s,
                "executable_09_30": True,
                "executable_15_00": True,
                "tail_signal_available_14_57": False,
            }
            for s in symbols
        ]
    )
    p = mod.CashPlatform(
        daily, minute, availability, [pd.Timestamp(day)], initial_cash=cash, lot_size=100, fee_bps=0
    )
    p.current_date = day
    p.event_stage = "open"
    return p


def test_cash_lot_partial_reduce_add_and_retry_state():
    p = platform()
    assert p.order_target_percent("A.SH", 0.60)
    assert p.order_target_percent("B.SH", 0.60)  # partial: only remaining cash is usable
    assert p.cash >= 0 and p.shares == {"A.SH": 6000, "B.SH": 4000}

    assert p.order_target_percent("A.SH", 1 / 3)  # reduction releases cash first
    assert p.order_target_percent("B.SH", 1 / 3)
    assert p.order_target_percent("C.SH", 1 / 3)
    assert p.cash >= 0 and set(p.positions) == {"A.SH", "B.SH", "C.SH"}

    p.availability = p.availability.drop(index=(p.current_date, "C.SH"))
    p.event_stage = "close"
    assert p.order_target("C.SH", 0) is None  # failed exit keeps state for retry
    assert "C.SH" in p.positions

    # Restore next-session availability and verify liquidation updates cash/state.
    p.availability.loc[
        (p.current_date, "C.SH"),
        ["executable_09_30", "executable_15_00", "tail_signal_available_14_57"],
    ] = [True, True, False]
    assert p.order_target("C.SH", 0)
    assert "C.SH" not in p.positions and p.cash >= 0


def test_insufficient_cash_is_rejected_not_negative():
    p = platform(cash=50)
    assert p.order_target_percent("A.SH", 0.5) is None
    assert p.cash == 50 and not p.positions
    assert p.events[-1]["reject_reason"] == "INSUFFICIENT_CASH_OR_LOT"
