from datetime import UTC, datetime

import pytest

from cyq_game.fundamentals import (
    FundamentalSnapshot,
    classify_fundamentals,
    unavailable_fundamentals,
)


def test_missing_pit_fundamentals_fail_closed_without_fabricated_score() -> None:
    state = unavailable_fundamentals()
    assert state.composite == 0.0
    assert state.coverage == 0.0
    assert state.contradictions == ("MISSING_PIT_FUNDAMENTALS",)


def test_zero_values_are_evidence_not_missing_defaults() -> None:
    state = classify_fundamentals(
        FundamentalSnapshot(
            revenue_growth=0.10,
            profit_growth=0.20,
            roe=0.12,
            operating_cashflow_to_profit=0.0,
            debt_ratio=0.0,
            valuation_percentile=0.0,
            earnings_revision=0.0,
            investment_growth=0.08,
            capital_return=0.0,
            audit_or_going_concern_risk=False,
            available_at=datetime(2024, 4, 30, 8, tzinfo=UTC),
            source="test",
        )
    )
    assert state.coverage == 1.0
    assert state.valuation == 1.0
    assert state.cash_flow_quality == 0.0
    assert "利润增长与经营现金流背离" in state.contradictions


def test_audit_risk_independently_blocks_new_risk() -> None:
    state = classify_fundamentals(
        FundamentalSnapshot(
            revenue_growth=0.15,
            profit_growth=0.20,
            roe=0.18,
            operating_cashflow_to_profit=1.1,
            debt_ratio=0.35,
            valuation_percentile=0.2,
            earnings_revision=0.03,
            investment_growth=0.08,
            capital_return=0.5,
            audit_or_going_concern_risk=True,
            available_at=datetime(2024, 4, 30, 8, tzinfo=UTC),
            source="test",
        )
    )
    assert state.blocks_new_risk
    assert state.balance_sheet_risk == 1.0
    assert state.composite == 0.0
    assert "审计或持续经营风险触发独立风控覆盖" in state.contradictions


def test_snapshot_requires_timestamp_and_source_lineage() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FundamentalSnapshot(
            revenue_growth=None,
            profit_growth=None,
            roe=None,
            operating_cashflow_to_profit=None,
            debt_ratio=None,
            valuation_percentile=None,
            earnings_revision=None,
            available_at=datetime(2024, 4, 30, 8),
            source="test",
        )
