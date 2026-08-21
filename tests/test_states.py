from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest

from cyq_game.chip.core import ChipState, CohortChipEngine, LogPriceGrid
from cyq_game.chip.features import ChipFeatures, compute_features
from cyq_game.data.asof_join import (
    REQUIRED_STRATEGY_DOMAINS,
    PITDomain,
    PITJoinResult,
)
from cyq_game.domain import RiskFlag
from cyq_game.state.classifier import (
    MarketPhase,
    RegimeClassifier,
    StockClassifier,
    StockEvidence,
    TacticalOverlay,
    classify_sector,
    classify_sectors_leave_one_out,
)
from cyq_game.state.strict import generate_strict_stock_state


def _features(quality: float = 0.70) -> ChipFeatures:
    grid = LogPriceGrid.around(8.0, 12.0)
    q = grid.volume_at_price(9.0, 11.0, 10.0)
    original = CohortChipEngine().initialize(grid, q, date(2024, 1, 2))
    state = ChipState(
        grid=original.grid,
        mass=original.mass,
        as_of=original.as_of,
        engine=original.engine,
        quality=quality,
        age_mass=original.age_mass,
    )
    return compute_features(state, open_price=9.9, high=10.2, low=9.7, close=10.1)


def test_market_six_phase_scores_hysteresis_and_overlays() -> None:
    classifier = RegimeClassifier(hysteresis=0.12)
    state = classifier.classify(
        trend=-0.20,
        breadth=0.15,
        volatility_percentile=0.95,
        liquidity=0.20,
        drawdown=-0.18,
        turnover_zscore=2.8,
    )
    assert set(state.phase_scores) == set(MarketPhase)
    assert state.phase in MarketPhase
    assert TacticalOverlay.OVERSOLD in state.overlays
    assert TacticalOverlay.LIQUIDITY_STRESS in state.overlays
    assert TacticalOverlay.CROWDING in state.overlays


def test_stock_is_multilabel_and_risk_is_independent() -> None:
    state = StockClassifier().classify(
        _features(quality=0.50),
        StockEvidence(
            return_20=0.08,
            distance_from_120d_low=0.20,
            control_score=0.90,
            base_retention=0.90,
            failed_breakout=True,
            data_quality=1.0,
        ),
    )
    assert state.types
    assert len({item.stock_type for item in state.types}) == len(state.types)
    assert RiskFlag.HARD_INVALID in state.risk.flags
    assert state.risk.blocks_new_risk
    assert state.reliability <= 0.50


def test_sector_uses_leave_one_out() -> None:
    state = classify_sector(
        member_returns={"TARGET": 1.0, "A": 0.01, "B": -0.01},
        market_return=0.0,
        positive_flow_share=0.5,
        turnover_concentration=0.2,
        excluded_symbol="TARGET",
    )
    assert state.member_count == 2
    assert state.relative_strength == 0.0


def test_sector_sparse_membership_shrinks_and_missing_fails_closed() -> None:
    sparse = classify_sector(
        member_returns={"TARGET": 0.50, "PEER": 0.20},
        market_return=0.0,
        member_amounts={"TARGET": 100.0, "PEER": 100.0},
        excluded_symbol="TARGET",
    )
    assert sparse.member_count == 1
    assert 0.0 < sparse.reliability < 0.2
    assert 0.5 < sparse.score < 0.6

    missing = classify_sector(
        member_returns={},
        market_return=0.0,
        member_amounts={},
        excluded_symbol="TARGET",
    )
    assert missing.member_count == 0
    assert missing.score == 0.5
    assert missing.reliability == 0.0


def test_batch_sector_leave_one_out_matches_individual_classification() -> None:
    returns = {"A": 0.03, "B": -0.01, "C": 0.02, "D": 0.00}
    amounts = {"A": 10.0, "B": 40.0, "C": 20.0, "D": 40.0}
    batch = classify_sectors_leave_one_out(
        member_returns=returns,
        market_return=0.005,
        member_amounts=amounts,
    )

    for symbol, batch_state in batch.items():
        individual = classify_sector(
            member_returns=returns,
            market_return=0.005,
            member_amounts=amounts,
            excluded_symbol=symbol,
        )
        assert batch_state.member_count == individual.member_count
        assert batch_state.relative_strength == pytest.approx(individual.relative_strength)
        assert batch_state.breadth == pytest.approx(individual.breadth)
        assert batch_state.capital_flow == pytest.approx(individual.capital_flow)
        assert batch_state.crowding == pytest.approx(individual.crowding)
        assert batch_state.score == pytest.approx(individual.score)
        assert batch_state.reliability == pytest.approx(individual.reliability)


def _pit_join_stub(*, hard_valid: bool, complete: bool = True) -> PITJoinResult:
    domains = (
        REQUIRED_STRATEGY_DOMAINS
        if complete
        else (PITDomain.SECURITY_IDENTITY,)
    )
    return cast(
        PITJoinResult,
        SimpleNamespace(
            request=SimpleNamespace(required_domains=domains),
            data_quality=1.0 if hard_valid else 0.5,
            hard_valid=hard_valid,
        ),
    )


def test_strict_state_requires_complete_hard_valid_pit_inputs() -> None:
    evidence = StockEvidence()
    chip = _features()

    assert generate_strict_stock_state(_pit_join_stub(hard_valid=False), chip, evidence) is None
    assert (
        generate_strict_stock_state(
            _pit_join_stub(hard_valid=True, complete=False), chip, evidence
        )
        is None
    )
    assert generate_strict_stock_state(_pit_join_stub(hard_valid=True), chip, evidence)


def test_strict_state_rejects_low_quality_inputs() -> None:
    result = generate_strict_stock_state(
        _pit_join_stub(hard_valid=True),
        _features(quality=0.50),
        StockEvidence(),
    )
    assert result is None
