from __future__ import annotations

import math
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.chinext_v1_exploratory import (  # noqa: E402
    ChinNextV1Config,
    breakout_volume_diagnostic,
    build_rs_table,
    can_sell,
    decide_next_open_fill,
    desired_target_weights,
    deterministic_equidistant_sample,
    entry_price_structure,
    full40_diagnostic,
    market_gate_state,
    minvol_diagnostic,
    own_exit_signal,
    select_no_replacement_members,
    set_change_required,
    sort_candidates,
    strict_breakout,
)
from scripts.run_chinext_v1_smoke import (  # noqa: E402
    PendingOrder,
    finite_or_default,
    schedule_target_set,
)


def oscillating_history(length: int, center: float = 100.0) -> list[float]:
    return [center + math.sin(index / 2.0) for index in range(length)]


def valid_execution_row(open_price: float = 10.0) -> dict[str, object]:
    return {
        "open": open_price,
        "hard_valid": True,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "buy_blocked_open": False,
        "sell_blocked_open": False,
    }


def test_b60_is_strictly_greater() -> None:
    closes = [100.0] * 60 + [100.0]
    assert not strict_breakout(closes, 60)
    closes[-1] = 100.01
    assert strict_breakout(closes, 60)


def test_b60_prior_window_excludes_signal_day() -> None:
    closes = list(range(1, 62))
    assert strict_breakout(closes, 60)


def test_full40_box_excludes_signal_day() -> None:
    config = replace(
        ChinNextV1Config(),
        vol_ratio_max=10.0,
        direction_efficiency_max=1.0,
    )
    closes = oscillating_history(121) + [1_000.0]
    diagnostic = full40_diagnostic(closes, config)
    assert diagnostic.valid
    assert diagnostic.box_width is not None and diagnostic.box_width < 0.03


def test_configurable_breakout_days_really_changes_signal() -> None:
    closes = oscillating_history(130)
    closes[-31] = 110.0
    closes[-1] = 105.0
    loose = replace(ChinNextV1Config(), breakout_days=20, vol_ratio_max=10.0, direction_efficiency_max=1.0)
    strict = replace(loose, breakout_days=60)
    assert entry_price_structure(closes, loose)[0]
    assert not entry_price_structure(closes, strict)[0]


def test_configurable_box_days_really_changes_window() -> None:
    closes = oscillating_history(130)
    closes[-42] = 80.0
    common = replace(
        ChinNextV1Config(),
        box_width_max=0.10,
        vol_ratio_max=10.0,
        direction_efficiency_max=1.0,
    )
    assert full40_diagnostic(closes, replace(common, box_days=40)).passed
    assert not full40_diagnostic(closes, replace(common, box_days=41)).passed


def test_configurable_exit_confirm_really_changes_signal() -> None:
    closes = [100.0] * 35 + [99.0, 101.0, 99.0]
    one = replace(ChinNextV1Config(), exit_ma=5, exit_confirm=1)
    two = replace(one, exit_confirm=2)
    assert own_exit_signal(closes, one)
    assert not own_exit_signal(closes, two)


def test_minvol_excludes_signal_day_volume() -> None:
    config = ChinNextV1Config()
    closes = list(range(1, 32))
    volumes = [10.0] * 30 + [1.0, 0.0]
    diagnostic = minvol_diagnostic(closes, volumes, config)
    assert diagnostic.valid
    assert diagnostic.minimum_volume == 1.0


def test_minvol_location_threshold() -> None:
    config = ChinNextV1Config()
    closes = [float(index) for index in range(1, 32)]
    volumes = [10.0] * 31
    volumes[29] = 1.0
    diagnostic = minvol_diagnostic(closes, volumes, config)
    assert not diagnostic.location_passed
    assert diagnostic.ratio_passed


def test_minvol_ratio_threshold() -> None:
    closes = [100.0] * 31
    volumes = [10.0] * 31
    diagnostic = minvol_diagnostic(closes, volumes, ChinNextV1Config())
    assert diagnostic.location_passed
    assert not diagnostic.ratio_passed
    assert not diagnostic.passed


def test_breakout_volume_denominator_is_prior_twenty_only() -> None:
    volumes = [10.0] * 20 + [30.0]
    diagnostic = breakout_volume_diagnostic(volumes, ChinNextV1Config())
    assert diagnostic.denominator == 10.0
    assert diagnostic.ratio == 3.0


def test_rs_uses_full_eligible_cross_section() -> None:
    histories = {
        "A": [100.0 + index * 0.1 for index in range(121)],
        "B": [100.0 + index * 0.2 for index in range(121)],
        "C": [100.0 + index * 0.3 for index in range(121)],
    }
    rows = build_rs_table(histories, {"A", "B", "C"}, ChinNextV1Config())
    assert set(rows) == {"A", "B", "C"}
    assert rows["C"]["r60"] == 1.0
    assert rows["A"]["r60"] == 1 / 3


def test_rs_score_uses_20_50_30_weights() -> None:
    histories = {
        "A": [100.0] * 121,
        "B": [100.0] * 100 + [float(80 + index) for index in range(21)],
    }
    rows = build_rs_table(histories, histories, ChinNextV1Config())
    row = rows["B"]
    expected = 0.20 * row["r20"] + 0.50 * row["r60"] + 0.30 * row["r120"]
    assert row["score"] == expected


def test_candidate_tie_break_is_score_then_mom60_then_symbol() -> None:
    rs = {
        "B": {"score": 0.8, "mom60": 0.2},
        "A": {"score": 0.8, "mom60": 0.2},
        "C": {"score": 0.8, "mom60": 0.3},
    }
    assert sort_candidates(rs, rs) == ["C", "A", "B"]


def test_max_ten_holdings() -> None:
    config = ChinNextV1Config()
    members = select_no_replacement_members([], [], [f"S{i:02d}" for i in range(12)], config)
    assert len(members) == 10


def test_each_desired_member_target_is_ten_percent() -> None:
    weights = desired_target_weights(["A", "B", "C"], ChinNextV1Config())
    assert weights == {"A": 0.1, "B": 0.1, "C": 0.1}


def test_fewer_than_ten_members_leave_cash() -> None:
    weights = desired_target_weights(["A", "B", "C", "D", "E"], ChinNextV1Config())
    assert sum(weights.values()) == 0.5


def test_set_change_only_ignores_price_drift() -> None:
    assert not set_change_required(["A", "B"], ["B", "A"])
    assert set_change_required(["A", "B"], ["A", "C"])


def test_no_replacement_when_portfolio_full() -> None:
    held = [f"S{i:02d}" for i in range(10)]
    desired = select_no_replacement_members(held, [], ["BEST"], ChinNextV1Config())
    assert set(desired) == set(held)


def test_ma30_two_close_exit() -> None:
    config = ChinNextV1Config()
    closes = [100.0] * 30 + [99.0, 98.0]
    assert own_exit_signal(closes, config)
    closes[-2] = 101.0
    assert not own_exit_signal(closes, config)


def test_t1_forbids_same_day_sell() -> None:
    acquired = date(2025, 1, 2)
    assert not can_sell(acquired, acquired)
    assert can_sell(acquired, acquired + timedelta(days=1))


def test_entry_fills_only_at_later_open() -> None:
    signal = date(2025, 1, 2)
    same_day = decide_next_open_fill(
        signal_date=signal,
        execution_date=signal,
        side="BUY",
        row=valid_execution_row(),
    )
    next_day = decide_next_open_fill(
        signal_date=signal,
        execution_date=signal + timedelta(days=1),
        side="BUY",
        row=valid_execution_row(10.5),
    )
    assert not same_day.filled
    assert next_day.filled and next_day.price == 10.5


def test_exit_fills_only_at_later_open() -> None:
    signal = date(2025, 1, 2)
    decision = decide_next_open_fill(
        signal_date=signal,
        execution_date=signal + timedelta(days=1),
        side="SELL",
        row=valid_execution_row(9.5),
        acquisition_date=date(2024, 12, 30),
    )
    assert decision.filled and decision.price == 9.5
    assert decision.t1_status == "PASS"


def test_missing_or_nonfinite_open_fails_closed() -> None:
    signal = date(2025, 1, 2)
    for row in (None, valid_execution_row(float("nan")), valid_execution_row(0.0)):
        decision = decide_next_open_fill(
            signal_date=signal,
            execution_date=signal + timedelta(days=1),
            side="BUY",
            row=row,
        )
        assert not decision.filled


def test_limit_or_suspension_blocks_open_fill() -> None:
    signal = date(2025, 1, 2)
    blocked = valid_execution_row()
    blocked["buy_blocked_open"] = True
    suspended = valid_execution_row()
    suspended["trade_status"] = 0
    for row in (blocked, suspended):
        assert not decide_next_open_fill(
            signal_date=signal,
            execution_date=signal + timedelta(days=1),
            side="BUY",
            row=row,
        ).filled


def test_market_gate_entry_and_exit_are_distinct() -> None:
    config = replace(ChinNextV1Config(), market_ma=3, market_exit_confirm=2)
    entry = market_gate_state([1.0, 1.0, 2.0, 3.0], config)
    assert entry["entry_permission"] and not entry["normal_exit"]
    exit_state = market_gate_state([3.0, 3.0, 3.0, 2.0, 1.0], config)
    assert not exit_state["entry_permission"] and exit_state["normal_exit"]


def test_deterministic_sample_is_sorted_equidistant_and_stable() -> None:
    symbols = [f"S{i:03d}" for i in range(100)]
    first = deterministic_equidistant_sample(symbols, 5)
    second = deterministic_equidistant_sample(list(reversed(symbols)), 5)
    assert first == second == ("S000", "S025", "S050", "S074", "S099")


def test_null_corporate_action_number_uses_neutral_default() -> None:
    assert finite_or_default(float("nan"), 0.0) == 0.0
    assert finite_or_default(None, 1.0) == 1.0
    assert finite_or_default(1.5, 1.0) == 1.5


def test_failed_pending_order_keeps_original_signal_lineage() -> None:
    original = PendingOrder("A", 0.1, date(2025, 1, 2), "ORIGINAL")
    pending = {"A": original}
    schedule_target_set(
        desired=("A", "B"),
        previous=("A",),
        positions={},
        pending=pending,
        signal_date=date(2025, 1, 3),
        reason="UNRELATED_SET_CHANGE",
        config=ChinNextV1Config(),
    )
    assert pending["A"] is original
    assert pending["B"].signal_date == date(2025, 1, 3)
