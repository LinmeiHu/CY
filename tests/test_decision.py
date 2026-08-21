from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest

from cyq_game.chip.core import ChipState, CohortChipEngine, LogPriceGrid
from cyq_game.chip.features import compute_features
from cyq_game.config import DecisionConfig, ExecutionConfig
from cyq_game.domain import Action, DecisionContext
from cyq_game.game.decision import (
    DecisionEngine,
    ParticipantKind,
    build_edge_card,
    build_scenarios,
    infer_participants,
)
from cyq_game.state.classifier import (
    MarketState,
    RegimeClassifier,
    StockClassifier,
    StockEvidence,
    StockState,
)

UTC = UTC


def _stock(*, quality: float = 0.75, failed_breakout: bool = False) -> StockState:
    grid = LogPriceGrid.around(8.0, 12.0)
    q = grid.volume_at_price(9.0, 11.0, 10.0)
    base = CohortChipEngine().initialize(grid, q, date(2024, 1, 2))
    chip = ChipState(grid, base.mass, base.as_of, base.engine, quality, base.age_mass)
    features = compute_features(chip, open_price=9.9, high=10.3, low=9.7, close=10.2)
    return StockClassifier().classify(
        features,
        StockEvidence(
            return_20=0.10,
            distance_from_120d_low=0.25,
            control_score=0.85,
            base_retention=0.90,
            relative_strength_percentile=0.85,
            failed_breakout=failed_breakout,
            data_quality=quality,
        ),
    )


def _market() -> MarketState:
    return RegimeClassifier().classify(
        trend=0.08,
        breadth=0.70,
        volatility_percentile=0.35,
        liquidity=0.80,
        drawdown=-0.02,
        turnover_zscore=0.4,
    )


def _context(**changes: float) -> DecisionContext:
    values: dict[str, Any] = {
        "data_quality": 0.90,
        "observability": 0.90,
        "execution_probability": 0.95,
        "market_confidence": 0.85,
        "sector_confidence": 0.80,
        "model_disagreement": 0.10,
    }
    values.update(changes)
    return DecisionContext(
        symbol="000001.SZ",
        decision_at=datetime(2024, 1, 3, 15, 31, tzinfo=UTC),
        **values,
    )


def test_participant_probabilities_and_observability_bound() -> None:
    ecology = infer_participants(_stock(), data_quality=0.40)
    assert set(ecology.probabilities) == set(ParticipantKind)
    assert sum(ecology.probabilities.values()) == pytest.approx(1.0)
    assert ecology.observability <= 0.40
    assert ecology.alternative_mass > 0.0


def test_unfrozen_fundamentals_are_absent_from_ecology_and_routing() -> None:
    stock = _stock()
    ecology = infer_participants(stock, fundamental_score=None, data_quality=0.90)
    assert ParticipantKind.FUNDAMENTAL_LONG not in ecology.probabilities
    assert sum(ecology.probabilities.values()) == pytest.approx(1.0)

    family, card = build_edge_card(stock, ecology, fundamental_score=None)
    assert family.value != "value_discovery"
    assert card is not None


def test_edge_card_scenarios_and_missing_card_fail_closed() -> None:
    stock = _stock()
    market = _market()
    context = _context()
    ecology = infer_participants(stock, data_quality=0.90)
    family, card = build_edge_card(stock, ecology, fundamental_score=0.65)
    assert card is not None and card.complete
    scenarios = build_scenarios(stock, market, context, card)
    assert len(scenarios) == 6
    assert sum(item.probability for item in scenarios) == pytest.approx(1.0)

    decision = DecisionEngine(DecisionConfig(), ExecutionConfig()).decide(
        stock=stock,
        market=market,
        context=context,
        ecology=ecology,
        edge_card=None,
        family=family,
        scenarios=(),
        price=10.0,
        order_value=10_000.0,
        adv_value=1_000_000.0,
    )
    assert decision.action == Action.NO_TRADE
    assert "EDGE_CARD_MISSING" in decision.gates


def test_incomplete_edge_card_fails_closed() -> None:
    stock = _stock()
    market = _market()
    context = _context()
    ecology = infer_participants(stock, data_quality=0.90)
    family, card = build_edge_card(stock, ecology)
    assert card is not None
    incomplete = replace(card, edge_source="")
    scenarios = build_scenarios(stock, market, context, incomplete)

    decision = DecisionEngine(DecisionConfig(), ExecutionConfig()).decide(
        stock=stock,
        market=market,
        context=context,
        ecology=ecology,
        edge_card=incomplete,
        family=family,
        scenarios=scenarios,
        price=10.0,
        order_value=10_000.0,
        adv_value=1_000_000.0,
    )

    assert decision.action == Action.NO_TRADE
    assert any(gate.startswith("EDGE_CARD_INCOMPLETE:") for gate in decision.gates)


def test_independent_risk_override_forbids_buy_and_add() -> None:
    stock = _stock(failed_breakout=True)
    market = _market()
    context = _context()
    ecology = infer_participants(stock, data_quality=0.90)
    family, card = build_edge_card(stock, ecology)
    assert card is not None
    scenarios = build_scenarios(stock, market, context, card)
    decision = DecisionEngine(DecisionConfig(), ExecutionConfig()).decide(
        stock=stock,
        market=market,
        context=context,
        ecology=ecology,
        edge_card=card,
        family=family,
        scenarios=scenarios,
        price=10.0,
        order_value=10_000.0,
        adv_value=1_000_000.0,
    )
    assert "INDEPENDENT_RISK_OVERRIDE" in decision.gates
    assert decision.action not in {Action.BUY, Action.ADD}
    assert decision.q_values[Action.BUY] == float("-inf")
