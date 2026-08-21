"""Interpretable state classifiers.

The scores here are evidence summaries, never trading instructions.  Thresholds are
configuration candidates and deliberately stay visible rather than being hidden in
an opaque model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import exp
from statistics import fmean

from cyq_game.chip.features import ChipFeatures
from cyq_game.domain import RiskFlag, RiskState, StateScore, StockType


def _clip(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + exp(-value))


class MarketPhase(StrEnum):
    PANIC = "panic"
    REPAIR = "repair"
    RANGE = "range"
    ADVANCE = "advance"
    OVERHEAT = "overheat"
    DISTRIBUTION = "distribution"


class TacticalOverlay(StrEnum):
    NONE = "none"
    OVERSOLD = "oversold"
    BREAKOUT = "breakout"
    CROWDING = "crowding"
    LIQUIDITY_STRESS = "liquidity_stress"


@dataclass(frozen=True)
class MarketState:
    phase: MarketPhase
    phase_scores: dict[MarketPhase, float]
    overlays: tuple[TacticalOverlay, ...]
    reliability: float
    breadth: float
    trend: float
    volatility_percentile: float
    liquidity: float
    reasons: tuple[str, ...]


class RegimeClassifier:
    """Six-phase market classifier with explicit hysteresis.

    A phase changes only when its score leads the incumbent by ``hysteresis``.
    """

    def __init__(self, hysteresis: float = 0.12) -> None:
        if not 0.0 <= hysteresis <= 0.5:
            raise ValueError("hysteresis must be in [0, 0.5]")
        self.hysteresis = hysteresis
        self._phase: MarketPhase | None = None

    def classify(
        self,
        *,
        trend: float,
        breadth: float,
        volatility_percentile: float,
        liquidity: float,
        drawdown: float,
        turnover_zscore: float,
        data_quality: float = 1.0,
    ) -> MarketState:
        """Classify normalized evidence.

        ``trend`` is roughly -1..1, breadth/liquidity/quality 0..1, drawdown is
        a non-positive return and turnover_zscore is an ordinary z-score.
        """

        breadth = _clip(breadth)
        volatility_percentile = _clip(volatility_percentile)
        liquidity = _clip(liquidity)
        quality = _clip(data_quality)
        scores = {
            MarketPhase.PANIC: _clip(
                0.40 * _sigmoid(-8.0 * (trend + 0.03))
                + 0.30 * _clip(-drawdown / 0.20)
                + 0.20 * volatility_percentile
                + 0.10 * (1.0 - liquidity)
            ),
            MarketPhase.REPAIR: _clip(
                0.35 * _sigmoid(8.0 * trend)
                + 0.30 * _clip((breadth - 0.35) / 0.40)
                + 0.20 * _clip(-drawdown / 0.20)
                + 0.15 * (1.0 - volatility_percentile)
            ),
            MarketPhase.RANGE: _clip(
                0.45 * (1.0 - _clip(abs(trend) / 0.08))
                + 0.30 * (1.0 - abs(breadth - 0.5) * 2.0)
                + 0.25 * (1.0 - volatility_percentile)
            ),
            MarketPhase.ADVANCE: _clip(
                0.45 * _sigmoid(10.0 * (trend - 0.02))
                + 0.35 * breadth
                + 0.20 * liquidity
            ),
            MarketPhase.OVERHEAT: _clip(
                0.35 * _sigmoid(12.0 * (trend - 0.08))
                + 0.25 * breadth
                + 0.25 * _sigmoid(turnover_zscore - 1.2)
                + 0.15 * volatility_percentile
            ),
            MarketPhase.DISTRIBUTION: _clip(
                0.30 * _sigmoid(2.0 * (turnover_zscore - 0.5))
                + 0.30 * _clip((0.55 - breadth) / 0.35)
                + 0.25 * volatility_percentile
                + 0.15 * _sigmoid(-8.0 * trend)
            ),
        }
        candidate = max(scores, key=scores.__getitem__)
        incumbent = self._phase
        if incumbent is not None and candidate != incumbent:
            if scores[candidate] < scores[incumbent] + self.hysteresis:
                candidate = incumbent
        self._phase = candidate

        overlays: list[TacticalOverlay] = []
        if drawdown < -0.10 and breadth < 0.30:
            overlays.append(TacticalOverlay.OVERSOLD)
        if trend > 0.06 and breadth > 0.62:
            overlays.append(TacticalOverlay.BREAKOUT)
        if turnover_zscore > 2.0:
            overlays.append(TacticalOverlay.CROWDING)
        if liquidity < 0.35:
            overlays.append(TacticalOverlay.LIQUIDITY_STRESS)
        if not overlays:
            overlays.append(TacticalOverlay.NONE)

        reasons = (
            f"trend={trend:.3f}",
            f"breadth={breadth:.3f}",
            f"vol_pct={volatility_percentile:.3f}",
            f"liquidity={liquidity:.3f}",
        )
        margin = scores[candidate] - sorted(scores.values())[-2]
        reliability = _clip(quality * (0.55 + 1.8 * max(0.0, margin)))
        return MarketState(
            phase=candidate,
            phase_scores=scores,
            overlays=tuple(overlays),
            reliability=reliability,
            breadth=breadth,
            trend=trend,
            volatility_percentile=volatility_percentile,
            liquidity=liquidity,
            reasons=reasons,
        )


@dataclass(frozen=True)
class SectorState:
    relative_strength: float
    breadth: float
    capital_flow: float
    crowding: float
    score: float
    reliability: float
    member_count: int


def classify_sector(
    *,
    member_returns: dict[str, float],
    market_return: float,
    positive_flow_share: float | None = None,
    turnover_concentration: float | None = None,
    member_amounts: dict[str, float] | None = None,
    excluded_symbol: str | None = None,
    shrinkage_members: float = 5.0,
) -> SectorState:
    """PIT sector evidence with leave-one-out aggregation and small-N shrinkage.

    When per-member amounts are supplied, capital-flow breadth and concentration
    are also recomputed after excluding the target.  Sparse industries shrink to
    a neutral score rather than receiving false confidence from one peer.
    """

    if shrinkage_members <= 0:
        raise ValueError("shrinkage_members must be positive")

    filtered_returns = {
        symbol: value
        for symbol, value in member_returns.items()
        if symbol != excluded_symbol
    }
    values = list(filtered_returns.values())
    if not values:
        return SectorState(0.0, 0.5, 0.5, 0.5, 0.5, 0.0, 0)
    weight = len(values) / (len(values) + shrinkage_members)
    sector_return = fmean(values)
    relative_strength = weight * (sector_return - market_return)
    raw_breadth = sum(value > market_return for value in values) / len(values)

    if member_amounts is not None:
        amounts = [
            max(0.0, member_amounts.get(symbol, 0.0))
            for symbol in filtered_returns
        ]
        total_amount = sum(amounts)
        raw_flow = sum(value > 0.0 for value in values) / len(values)
        raw_crowding = (
            max(amounts, default=0.0) / total_amount if total_amount > 0.0 else 1.0
        )
    else:
        raw_flow = 0.5 if positive_flow_share is None else _clip(positive_flow_share)
        raw_crowding = (
            0.5 if turnover_concentration is None else _clip(turnover_concentration)
        )
    breadth = weight * raw_breadth + (1.0 - weight) * 0.5
    flow = weight * raw_flow + (1.0 - weight) * 0.5
    crowding = weight * raw_crowding + (1.0 - weight) * 0.5
    raw_score = _clip(
        0.35 * _sigmoid(relative_strength * 30.0)
        + 0.35 * breadth
        + 0.20 * flow
        + 0.10 * (1.0 - crowding)
    )
    score = weight * raw_score + (1.0 - weight) * 0.5
    reliability = weight * (1.0 - 0.35 * crowding)
    return SectorState(
        relative_strength=relative_strength,
        breadth=breadth,
        capital_flow=flow,
        crowding=crowding,
        score=score,
        reliability=reliability,
        member_count=len(values),
    )


def classify_sectors_leave_one_out(
    *,
    member_returns: dict[str, float],
    market_return: float,
    member_amounts: dict[str, float] | None = None,
    shrinkage_members: float = 5.0,
) -> dict[str, SectorState]:
    """Classify every member with one industry scan and O(1) leave-one-out work."""

    if shrinkage_members <= 0:
        raise ValueError("shrinkage_members must be positive")
    if not member_returns:
        return {}

    symbols = tuple(member_returns)
    count = len(symbols)
    return_sum = sum(member_returns.values())
    above_market_count = sum(value > market_return for value in member_returns.values())
    positive_count = sum(value > 0.0 for value in member_returns.values())
    amounts = {
        symbol: max(0.0, (member_amounts or {}).get(symbol, 0.0)) for symbol in symbols
    }
    amount_sum = sum(amounts.values())
    ranked_amounts = sorted(amounts.values(), reverse=True)
    largest_amount = ranked_amounts[0] if ranked_amounts else 0.0
    second_largest_amount = ranked_amounts[1] if len(ranked_amounts) > 1 else 0.0

    states: dict[str, SectorState] = {}
    for symbol in symbols:
        peer_count = count - 1
        if peer_count == 0:
            states[symbol] = SectorState(0.0, 0.5, 0.5, 0.5, 0.5, 0.0, 0)
            continue
        weight = peer_count / (peer_count + shrinkage_members)
        symbol_return = member_returns[symbol]
        sector_return = (return_sum - symbol_return) / peer_count
        relative_strength = weight * (sector_return - market_return)
        raw_breadth = (
            above_market_count - int(symbol_return > market_return)
        ) / peer_count
        raw_flow = (positive_count - int(symbol_return > 0.0)) / peer_count
        symbol_amount = amounts[symbol]
        peer_amount_sum = amount_sum - symbol_amount
        peer_max_amount = (
            second_largest_amount
            if symbol_amount == largest_amount
            else largest_amount
        )
        raw_crowding = (
            peer_max_amount / peer_amount_sum if peer_amount_sum > 0.0 else 1.0
        )
        breadth = weight * raw_breadth + (1.0 - weight) * 0.5
        flow = weight * raw_flow + (1.0 - weight) * 0.5
        crowding = weight * raw_crowding + (1.0 - weight) * 0.5
        raw_score = _clip(
            0.35 * _sigmoid(relative_strength * 30.0)
            + 0.35 * breadth
            + 0.20 * flow
            + 0.10 * (1.0 - crowding)
        )
        states[symbol] = SectorState(
            relative_strength=relative_strength,
            breadth=breadth,
            capital_flow=flow,
            crowding=crowding,
            score=weight * raw_score + (1.0 - weight) * 0.5,
            reliability=weight * (1.0 - 0.35 * crowding),
            member_count=peer_count,
        )
    return states


@dataclass(frozen=True)
class StockEvidence:
    """Price/volume/context evidence used alongside the chip features."""

    return_5: float = 0.0
    return_20: float = 0.0
    return_60: float = 0.0
    drawdown_20: float = 0.0
    volatility_percentile: float = 0.5
    turnover_zscore: float = 0.0
    volume_contraction: float = 0.0
    relative_strength_percentile: float = 0.5
    base_retention: float = 0.5
    valley_fill: float = 0.0
    distance_from_120d_low: float = 0.5
    control_score: float = 0.5
    prior_control_score: float = 0.5
    market_breadth: float = 0.5
    sector_score: float = 0.5
    group_oversold: float = 0.0
    new_high: bool = False
    failed_breakout: bool = False
    rebound_from_low: float = 0.0
    intraday_confirmation: float = 0.5
    intraday_conflict: float = 0.0
    intraday_attention: float = 0.0
    data_quality: float = 1.0


@dataclass(frozen=True)
class StockState:
    types: tuple[StateScore, ...]
    primary: StockType
    risk: RiskState
    reliability: float
    evidence: dict[str, float | bool]
    explanations: tuple[str, ...] = field(default_factory=tuple)

    def score(self, stock_type: StockType) -> float:
        return next(
            (item.score for item in self.types if item.stock_type == stock_type), 0.0
        )


class StockClassifier:
    """Multi-label T0--T9 state recognition with an independent risk overlay."""

    def classify(self, chip: ChipFeatures, ev: StockEvidence) -> StockState:
        low = _clip(1.0 - ev.distance_from_120d_low)
        high = _clip(ev.distance_from_120d_low)
        control = _clip(ev.control_score)
        locked = _clip(
            chip.concentration_20 * 0.55
            + chip.asr * 0.25
            + (1.0 - _clip(chip.cbw / 100.0)) * 0.20
        )
        profit = _clip(chip.pr)
        trend = _sigmoid(ev.return_20 * 18.0)
        oversold = _clip(
            0.35 * _clip(-ev.return_20 / 0.20)
            + 0.25 * _clip(-(chip.cys13 or 0.0) / 22.0)
            + 0.20 * ev.group_oversold
            + 0.20 * (1.0 - profit)
        )
        rescue = _clip(
            0.30 * _clip(-ev.drawdown_20 / 0.25)
            + 0.25 * ev.rebound_from_low
            + 0.20 * _sigmoid(ev.turnover_zscore)
            + 0.20 * ev.prior_control_score
            + 0.05 * ev.intraday_confirmation
        )
        scores = {
            StockType.T0: _clip(
                0.30 * low
                + 0.25 * control
                + 0.20 * ev.volume_contraction
                + 0.15 * ev.base_retention
                + 0.10 * (1.0 - trend)
            ),
            StockType.T1: _clip(
                0.30 * (1.0 if len(chip.peaks) >= 2 else 0.0)
                + 0.30 * ev.valley_fill
                + 0.20 * ev.base_retention
                + 0.20 * _sigmoid(ev.turnover_zscore)
            ),
            StockType.T2: _clip(
                0.30 * low
                + 0.35 * control
                + 0.20 * locked
                + 0.15 * trend
            ),
            StockType.T3: _clip(
                0.25 * low
                + 0.30 * locked
                + 0.20 * trend
                + 0.20 * ev.relative_strength_percentile
                + 0.05 * ev.intraday_confirmation
            ),
            StockType.T4: _clip(
                0.25 * high
                + 0.25 * ev.relative_strength_percentile
                + 0.15 * (1.0 if ev.new_high else 0.0)
                + 0.15 * locked
                + 0.15 * (1.0 - ev.market_breadth)
                + 0.05 * ev.intraday_confirmation
            ),
            StockType.T5: rescue,
            StockType.T6: _clip(0.70 * oversold + 0.30 * (1.0 - control)),
            StockType.T7: _clip(
                0.25 * (1.0 - abs(high - 0.55) * 2.0)
                + 0.30 * control
                + 0.25 * trend
                + 0.20 * _sigmoid(ev.turnover_zscore)
            ),
            StockType.T8: _clip(
                0.30 * high
                + 0.25 * trend
                + 0.20 * (1.0 - control)
                + 0.15 * _sigmoid(ev.turnover_zscore)
                + 0.10 * ev.sector_score
            ),
            StockType.T9: _clip(
                0.30 * high
                + 0.30 * control
                + 0.20 * (1.0 - abs(ev.return_20) / 0.12)
                + 0.20 * ev.base_retention
            ),
        }
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        state_scores = tuple(
            StateScore(stock_type=stock_type, score=score, reliability=0.0)
            for stock_type, score in ranked
            if score >= 0.45 or stock_type == ranked[0][0]
        )
        margin = ranked[0][1] - ranked[1][1]
        reliability = _clip(
            min(chip.quality, ev.data_quality)
            * (0.55 + 1.5 * margin)
            * (0.85 if len(state_scores) > 3 else 1.0)
            * (1.0 - 0.25 * _clip(ev.intraday_conflict))
        )
        state_scores = tuple(
            StateScore(item.stock_type, item.score, reliability, item.evidence)
            for item in state_scores
        )

        risk_flags: list[RiskFlag] = []
        risk_reasons: list[str] = []
        distribution_score = _clip(
            0.25 * _sigmoid(ev.turnover_zscore - 0.5)
            + 0.20 * high
            + 0.20 * _clip(-ev.return_5 / 0.10)
            + 0.20 * (1.0 - ev.base_retention)
            + 0.15 * ev.intraday_conflict
        )
        if ev.failed_breakout or distribution_score >= 0.65:
            risk_flags.append(
                RiskFlag.SECONDARY_HIGH_DISTRIBUTION
                if high > 0.60
                else RiskFlag.HORIZONTAL_DISTRIBUTION
            )
            risk_reasons.append("放量滞涨/突破失败与底仓流失形成派发证据")
        if ev.volatility_percentile > 0.90:
            risk_reasons.append("波动率处于极端分位")
        if ev.turnover_zscore > 2.5:
            risk_reasons.append("换手拥挤，反身性与冲击成本上升")
        if chip.quality < 0.55 or ev.data_quality < 0.55:
            risk_flags.append(RiskFlag.HARD_INVALID)
            risk_reasons.append("筹码或行情输入质量不足")
        risk_score = _clip(
            max(
                distribution_score,
                ev.volatility_percentile if ev.volatility_percentile > 0.90 else 0.0,
                1.0 - min(chip.quality, ev.data_quality),
            )
        )
        risk = RiskState(
            flags=frozenset(risk_flags),
            hard_valid=RiskFlag.HARD_INVALID not in risk_flags,
            tail_loss_r=2.0 * risk_score,
            reasons=tuple(risk_reasons),
        )
        explanations = (
            f"primary={ranked[0][0].value}, score={ranked[0][1]:.3f}",
            f"control={control:.3f}, locked={locked:.3f}, profit={profit:.3f}",
            f"low={low:.3f}, trend={trend:.3f}, oversold={oversold:.3f}",
        )
        return StockState(
            types=state_scores,
            primary=ranked[0][0],
            risk=risk,
            reliability=reliability,
            evidence={
                "low": low,
                "high": high,
                "control": control,
                "locked": locked,
                "profit": profit,
                "trend": trend,
                "oversold": oversold,
                "distribution": distribution_score,
            },
            explanations=explanations,
        )
