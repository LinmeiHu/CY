from __future__ import annotations

from datetime import date

import pytest

from cyq_game.backtest.diagnostics import build_research_diagnostics
from cyq_game.domain import OrderSide
from cyq_game.execution.simulator import Fill


def test_research_diagnostics_do_not_mislabel_gate_counts_as_performance() -> None:
    fill = Fill(
        order_id="o1",
        symbol="000001.SZ",
        trade_date=date(2024, 1, 2),
        side=OrderSide.BUY,
        quantity=100,
        price=10.0,
        commission=0.3,
        stamp_duty=0.0,
        slippage=0.5,
        impact=0.2,
        participation=0.02,
    )
    diagnostics = build_research_diagnostics(
        equity=[100_000.0, 101_000.0],
        fills=[fill],
        decisions=[{"action": "NO_TRADE", "gates": ["OBSERVABILITY_BELOW_GATE"]}],
        total_cost=100.0,
        participation_cap=0.05,
    )
    assert diagnostics["cost_stress"][0]["cost_multiplier"] == 0.5
    assert diagnostics["cost_stress"][0]["stressed_final_equity"] == pytest.approx(
        101_050.0
    )
    assert diagnostics["cost_stress"][2]["stressed_final_equity"] == pytest.approx(
        100_950.0
    )
    assert diagnostics["cost_stress"][3]["stressed_final_equity"] == pytest.approx(
        100_900.0
    )
    assert diagnostics["capacity"]["max_realized_participation"] == pytest.approx(0.02)
    gates = diagnostics["gate_attribution"]
    assert gates["method"] == "decision_gate_attribution_not_performance_ablation"
    assert "fresh PIT-safe walk-forward" in gates["warning"]
