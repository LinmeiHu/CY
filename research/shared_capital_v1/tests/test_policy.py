"""Focused arithmetic and blocker tests; these do NOT certify historical replay."""
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from shared_account.allocator import (
    active_strategies, base_headroom, capped_headroom, exact_confirmation,
    native_lot_floor, proportional_cash,
)
from shared_account.drawdown_gate import DrawdownGate
from run_shared_capital_v1 import POLICY, scenario_grid, source_evidence
from five_strategy_bundle.strategies.ogr import select_v27


def test_exact_24_scenarios_each_period():
    policy = json.loads(POLICY.read_text())
    scenarios = scenario_grid(policy)
    assert len(scenarios) == 48
    assert len({tuple(s.values()) for s in scenarios}) == 48
    assert all(sum(s["period"] == period for s in scenarios) == 24 for period in policy["periods"])


def test_gap_exclusive():
    assert active_strategies("OGR") == ("ATRDR", "MCB", "OGR", "SMV6")
    assert active_strategies("IFCGR") == ("ATRDR", "MCB", "IFCGR", "SMV6")
    with pytest.raises(ValueError):
        active_strategies("OGR+IFCGR")


def test_entitlement_does_not_accept_shared_profit_input():
    assert base_headroom(1000000, 800000) == 200000
    with pytest.raises(TypeError):
        base_headroom(1000000, 800000, shared_profit=100000)
    assert base_headroom(1000000, 1100000) == 0


def test_demand_family_cannot_net_borrow():
    home = {s: 100 for s in active_strategies("OGR")}
    exposure = {"ATRDR": 100, "MCB": 100, "OGR": 0, "SMV6": 0}
    assert capped_headroom("ATRDR", home, exposure) == 0
    assert capped_headroom("OGR", home, exposure) == 150
    exposure["MCB"] = 50
    assert capped_headroom("ATRDR", home, exposure) == 50


def test_market_drift_only_removes_new_headroom():
    home = {s: 100 for s in active_strategies("OGR")}
    exposure = {s: 160 for s in home}
    before = exposure.copy()
    assert capped_headroom("OGR", home, exposure) == 0
    assert exposure == before


def test_unmet_proportions_not_return_ranking():
    assert proportional_cash(100, {"MCB": 300, "ATRDR": 100}) == {"ATRDR": Decimal(25), "MCB": Decimal(75)}
    assert proportional_cash(1000, {"MCB": 300, "ATRDR": 100}) == {"ATRDR": Decimal(100), "MCB": Decimal(300)}
    assert proportional_cash(100, {"MCB": 0}) == {"MCB": Decimal(0)}


def test_proportions_deterministic_across_insertion_order():
    assert proportional_cash(47, {"MCB": 27, "ATRDR": 88}) == proportional_cash(47, {"ATRDR": 88, "MCB": 27})


@pytest.mark.parametrize("budget,requested,unit,expected", [(110, 100, 30, 3), (0, 100, 30, 0), (100, 0, 30, 0), (100, 100, 25, 4)])
def test_native_requested_notional_ceiling(budget, requested, unit, expected):
    funded = native_lot_floor(budget, requested, unit)
    assert funded == expected
    assert funded * unit <= min(requested, budget)


def overlap():
    a = dict(strategy="ATRDR", route="BULL", symbol="600001.SH", direction="LONG", decision_timestamp="2021-01-04T15:00:00", entry_session="2021-01-05", economic_event_definition="E1")
    return a, {**a, "strategy": "MCB"}


def test_exact_parent_confirmed():
    a, b = overlap()
    a["parent_event_id"] = b["parent_event_id"] = "PARENT1"
    assert exact_confirmation(a, b)
    b["direction"] = "SHORT"
    assert not exact_confirmation(a, b)


def test_time_proximity_is_not_identity():
    a, b = overlap()
    assert exact_confirmation(a, b)
    b["decision_timestamp"] = "2021-01-05T15:00:00"
    assert not exact_confirmation(a, b)


def test_missing_economic_identity_is_not_overlap():
    a, b = overlap()
    del b["economic_event_definition"]
    assert not exact_confirmation(a, b)


def test_bear_cannot_be_confirmation_target():
    a, b = overlap()
    a["route"] = "FAST_BEAR"
    assert not exact_confirmation(a, b)


@pytest.mark.parametrize("D", [0.04, 0.05, 0.06])
def test_gate_exact_thresholds_and_overshoot(D):
    gate = DrawdownGate(D, 100)
    day = date(2021, 1, 4)
    assert gate.complete_close(day, 100 * (1 - .5 * D)) == .75
    assert gate.complete_close(day + timedelta(days=1), 100 * (1 - .75 * D)) == .5
    assert gate.complete_close(day + timedelta(days=2), 100 * (1 - D)) == 0
    assert gate.complete_close(day + timedelta(days=3), 100 * (1 - 1.5 * D)) == 0
    # Gate does not overwrite NAV to impose a fictitious D maximum loss.
    assert gate.high == 100


def test_gate_three_day_recovery_one_level_at_a_time():
    gate = DrawdownGate(.05, 100)
    day = date(2021, 1, 4)
    assert gate.complete_close(day, 94) == 0
    for i, expected in enumerate([0, 0, .5, .5, .5, .75, .75, .75, 1], 1):
        assert gate.complete_close(day + timedelta(days=i), 100) == expected


def test_gate_recovery_requires_margin_and_resets_streak():
    gate = DrawdownGate(.05, 100)
    day = date(2021, 1, 4)
    gate.complete_close(day, 94)
    for i, nav in enumerate([95.5, 95.5, 95.4, 95.5, 95.5], 1):
        assert gate.complete_close(day + timedelta(days=i), nav) == 0
    assert gate.complete_close(day + timedelta(days=6), 95.5) == .5


def test_gate_rejects_duplicate_close():
    gate = DrawdownGate(.05, 100)
    gate.complete_close(date(2021, 1, 4), 98)
    with pytest.raises(ValueError):
        gate.complete_close(date(2021, 1, 4), 100)


def test_accounts_initialize_independently():
    first, second = DrawdownGate(.05, 4000000), DrawdownGate(.05, 4000000)
    first.complete_close(date(2021, 12, 31), 3600000)
    assert second.high == 4000000 and second.multiplier == 1 and second.last_close is None


def test_no_extra_gate_threshold():
    with pytest.raises(ValueError):
        DrawdownGate(.045, 100)


def test_actual_sealed_gap_selector_excludes_valid_2022_candidate():
    base = dict(gap_age=5, max_depth=.2, current_depth=.1, pre_peak_to_gap_sessions=30, symbol="600001.SH")
    candidates = pd.DataFrame([
        {**base, "gap_id": str(year), "signal_date": pd.Timestamp(f"{year}-06-01"), "signal_time": pd.Timestamp(f"{year}-06-01 15:00:00")}
        for year in (2021, 2022, 2023)
    ])
    result = select_v27(candidates)
    assert result.gap_id.tolist() == ["2021"]


def test_blocker_evidence_contains_exact_ifcgr_cutoff():
    rows = source_evidence()
    assert any("causal_available_at<TIMESTAMP '2022-01-01'" in r["evidence"] for r in rows)
