"""Point-in-time fundamental attribution and state.

This module intentionally does not fabricate intrinsic values.  It combines only
the fields supplied by a PIT fundamental adapter and reports missing evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class FundamentalSnapshot:
    """One disclosed, revision-aware fundamental observation.

    Growth, leverage, revisions and capital-return inputs are decimal ratios.
    ``valuation_percentile`` is the industry-neutral percentile in ``[0, 1]``;
    lower is cheaper. ``capital_return`` is a signed score in ``[-1, 1]`` where
    dividends/buybacks are positive and dilution is negative.
    """

    revenue_growth: float | None
    profit_growth: float | None
    roe: float | None
    operating_cashflow_to_profit: float | None
    debt_ratio: float | None
    valuation_percentile: float | None
    earnings_revision: float | None
    available_at: datetime
    source: str
    period_end: date | None = None
    effective_from: date | None = None
    investment_growth: float | None = None
    capital_return: float | None = None
    audit_or_going_concern_risk: bool | None = None
    snapshot_id: str = ""
    revision_id: str = ""

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("fundamental available_at must be timezone-aware")
        if not self.source:
            raise ValueError("fundamental source must be non-empty")
        numeric = (
            self.revenue_growth,
            self.profit_growth,
            self.roe,
            self.operating_cashflow_to_profit,
            self.debt_ratio,
            self.valuation_percentile,
            self.earnings_revision,
            self.investment_growth,
            self.capital_return,
        )
        if any(value is not None and not isfinite(value) for value in numeric):
            raise ValueError("fundamental inputs must be finite when supplied")
        if self.debt_ratio is not None and not 0.0 <= self.debt_ratio <= 1.0:
            raise ValueError("debt_ratio must be in [0, 1]")
        if (
            self.valuation_percentile is not None
            and not 0.0 <= self.valuation_percentile <= 1.0
        ):
            raise ValueError("valuation_percentile must be in [0, 1]")
        if self.capital_return is not None and not -1.0 <= self.capital_return <= 1.0:
            raise ValueError("capital_return must be in [-1, 1]")


@dataclass(frozen=True)
class FundamentalState:
    quality: float
    growth: float
    valuation: float
    revision: float
    profitability: float
    cash_flow_quality: float
    investment_growth: float
    balance_sheet_risk: float
    capital_return: float
    composite: float
    coverage: float
    blocks_new_risk: bool
    contradictions: tuple[str, ...]


def unavailable_fundamentals() -> FundamentalState:
    """Return a fail-closed state when no PIT fundamental adapter supplied evidence."""

    return FundamentalState(
        quality=0.0,
        growth=0.0,
        valuation=0.0,
        revision=0.0,
        profitability=0.0,
        cash_flow_quality=0.0,
        investment_growth=0.0,
        balance_sheet_risk=0.0,
        capital_return=0.0,
        composite=0.0,
        coverage=0.0,
        blocks_new_risk=False,
        contradictions=("MISSING_PIT_FUNDAMENTALS",),
    )


def classify_fundamentals(snapshot: FundamentalSnapshot) -> FundamentalState:
    fields = (
        snapshot.revenue_growth,
        snapshot.profit_growth,
        snapshot.roe,
        snapshot.operating_cashflow_to_profit,
        snapshot.debt_ratio,
        snapshot.valuation_percentile,
        snapshot.earnings_revision,
        snapshot.investment_growth,
        snapshot.capital_return,
        snapshot.audit_or_going_concern_risk,
    )
    coverage = sum(value is not None for value in fields) / len(fields)
    growth = _clip(
        0.5
        + 1.5 * (snapshot.revenue_growth or 0.0)
        + 1.5 * (snapshot.profit_growth or 0.0)
    )
    profitability = _clip(
        0.25
        + 2.8 * (snapshot.roe or 0.0)
        + 0.5 * max(snapshot.profit_growth or 0.0, 0.0)
    )
    cash_flow_quality = _clip((snapshot.operating_cashflow_to_profit or 0.0) / 1.2)
    if snapshot.investment_growth is None:
        investment_growth = 0.0
    else:
        # Moderate reinvestment receives credit; contraction and explosive,
        # potentially inventory-led expansion do not automatically look good.
        investment_growth = _clip(1.0 - abs(snapshot.investment_growth - 0.08) / 0.35)
    balance_sheet_risk = _clip(
        (snapshot.debt_ratio or 0.0)
        + (0.65 if snapshot.audit_or_going_concern_risk else 0.0)
    )
    capital_return = (
        _clip(0.5 + 0.5 * snapshot.capital_return)
        if snapshot.capital_return is not None
        else 0.0
    )
    quality = _clip(
        0.45 * profitability
        + 0.35 * cash_flow_quality
        + 0.20 * (1.0 - balance_sheet_risk)
    )
    valuation_percentile = (
        snapshot.valuation_percentile
        if snapshot.valuation_percentile is not None
        else 0.5
    )
    valuation = _clip(1.0 - valuation_percentile)
    revision = _clip(0.5 + 2.5 * (snapshot.earnings_revision or 0.0))
    contradictions: list[str] = []
    operating_cashflow_to_profit = (
        snapshot.operating_cashflow_to_profit
        if snapshot.operating_cashflow_to_profit is not None
        else 1.0
    )
    if (snapshot.profit_growth or 0.0) > 0.15 and operating_cashflow_to_profit < 0.6:
        contradictions.append("利润增长与经营现金流背离")
    if (snapshot.revenue_growth or 0.0) < 0.0 and (
        snapshot.profit_growth or 0.0
    ) > 0.2:
        contradictions.append("收入下降但利润高增，需核查非经常项")
    if (snapshot.debt_ratio or 0.0) > 0.85:
        contradictions.append("高杠杆资产负债表")
    if snapshot.audit_or_going_concern_risk:
        contradictions.append("审计或持续经营风险触发独立风控覆盖")
    blocks_new_risk = snapshot.audit_or_going_concern_risk is True
    composite = (
        0.0
        if blocks_new_risk
        else _clip(
            coverage
            * (
                0.18 * profitability
                + 0.13 * revision
                + 0.15 * cash_flow_quality
                + 0.09 * investment_growth
                + 0.17 * valuation
                + 0.10 * capital_return
                + 0.09 * growth
                + 0.09 * (1.0 - balance_sheet_risk)
            )
            - 0.10 * len(contradictions)
        )
    )
    return FundamentalState(
        quality=quality,
        growth=growth,
        valuation=valuation,
        revision=revision,
        profitability=profitability,
        cash_flow_quality=cash_flow_quality,
        investment_growth=investment_growth,
        balance_sheet_risk=balance_sheet_risk,
        capital_return=capital_return,
        composite=composite,
        coverage=coverage,
        blocks_new_risk=blocks_new_risk,
        contradictions=tuple(contradictions),
    )
