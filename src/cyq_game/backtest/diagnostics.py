from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from cyq_game.execution import Fill


class DecisionGateAccumulator:
    """Streaming gate attribution so full runs do not retain every decision."""

    def __init__(self) -> None:
        self._decision_count = 0
        self._no_trade_count = 0
        self._gate_counts: Counter[str] = Counter()
        self._sole_gate_no_trade: Counter[str] = Counter()

    def observe(self, row: Mapping[str, Any]) -> None:
        gates = [_gate_family(str(gate)) for gate in row.get("gates", [])]
        self._decision_count += 1
        self._gate_counts.update(gates)
        if row.get("action") == "NO_TRADE":
            self._no_trade_count += 1
            unique = sorted(set(gates))
            if len(unique) == 1:
                self._sole_gate_no_trade[unique[0]] += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "decision_gate_attribution_not_performance_ablation",
            "warning": (
                "Counts show observed decision blocks only; removing a gate requires "
                "a fresh PIT-safe walk-forward run before any performance claim."
            ),
            "decision_count": self._decision_count,
            "no_trade_count": self._no_trade_count,
            "gate_occurrences": dict(sorted(self._gate_counts.items())),
            "sole_gate_no_trade_candidates": dict(sorted(self._sole_gate_no_trade.items())),
        }


def build_research_diagnostics(
    *,
    equity: Sequence[float],
    fills: Sequence[Fill],
    decisions: Sequence[Mapping[str, Any]] = (),
    gate_attribution: Mapping[str, Any] | None = None,
    total_cost: float,
    participation_cap: float,
    cost_multipliers: Iterable[float] = (0.5, 1.0, 1.5, 2.0),
) -> dict[str, Any]:
    """Create transparent sensitivity diagnostics without reusing the holdout.

    Cost stress is a cash-flow sensitivity, capacity uses realized fills, and the
    ablation section is gate attribution only.  None of these is represented as
    an independently re-run strategy performance estimate.
    """

    initial_equity = float(equity[0]) if equity else 0.0
    final_equity = float(equity[-1]) if equity else initial_equity
    cost_stress = []
    for multiplier in cost_multipliers:
        if multiplier < 0.0:
            raise ValueError("cost stress multipliers must be non-negative")
        stressed_final = final_equity - total_cost * (multiplier - 1.0)
        cost_stress.append(
            {
                "cost_multiplier": multiplier,
                "incremental_cost": total_cost * (multiplier - 1.0),
                "stressed_final_equity": stressed_final,
                "stressed_total_return": (
                    stressed_final / initial_equity - 1.0 if initial_equity > 0 else 0.0
                ),
            }
        )

    participation = sorted(fill.participation for fill in fills)
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for fill in fills:
        by_symbol[fill.symbol].append(fill.participation)
    capacity = {
        "fill_count": len(participation),
        "configured_participation_cap": participation_cap,
        "mean_realized_participation": (
            sum(participation) / len(participation) if participation else 0.0
        ),
        "p95_realized_participation": _percentile(participation, 0.95),
        "max_realized_participation": max(participation, default=0.0),
        "fills_above_80pct_of_cap": sum(value > participation_cap * 0.8 for value in participation),
        "per_symbol_max": {symbol: max(values) for symbol, values in sorted(by_symbol.items())},
    }

    if gate_attribution is None:
        accumulator = DecisionGateAccumulator()
        for row in decisions:
            accumulator.observe(row)
        gate_attribution = accumulator.to_dict()
    return {
        "methodology": "development-sample diagnostics; final holdout remains locked",
        "cost_stress": cost_stress,
        "capacity": capacity,
        "gate_attribution": gate_attribution,
    }


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be in [0, 1]")
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction


def _gate_family(gate: str) -> str:
    return gate.split(":", 1)[0]
