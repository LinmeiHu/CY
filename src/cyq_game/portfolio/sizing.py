from __future__ import annotations

from dataclasses import dataclass

from cyq_game.config import PortfolioConfig


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class CalibratedForecast:
    win_probability: float
    average_win_r: float
    average_loss_r: float
    sample_size: int
    out_of_sample: bool
    calibration_error: float = 0.0

    @property
    def valid(self) -> bool:
        return (
            self.out_of_sample
            and self.sample_size >= 30
            and 0.0 < self.win_probability < 1.0
            and self.average_win_r > 0.0
            and self.average_loss_r > 0.0
            and 0.0 <= self.calibration_error <= 0.20
        )


@dataclass(frozen=True)
class PortfolioConstraints:
    equity: float
    cash: float
    current_name_fraction: float
    current_sector_fraction: float
    current_theme_fraction: float
    adv_value: float
    edge_capacity_fraction_adv: float
    drawdown: float
    reliability: float
    observability: float
    execution_probability: float
    market_confidence: float
    sector_confidence: float


@dataclass(frozen=True)
class SizeDecision:
    target_fraction: float
    incremental_value: float
    unconstrained_kelly: float
    applied_caps: tuple[str, ...]
    rejected_reason: str | None = None


def fractional_kelly_size(
    forecast: CalibratedForecast,
    constraints: PortfolioConstraints,
    config: PortfolioConfig,
) -> SizeDecision:
    """Size with fractional Kelly followed by every independent cap."""

    if not forecast.valid:
        return SizeDecision(0.0, 0.0, 0.0, (), "FORECAST_NOT_OOS_CALIBRATED")
    if constraints.equity <= 0 or constraints.cash < 0 or constraints.adv_value <= 0:
        return SizeDecision(0.0, 0.0, 0.0, (), "INVALID_PORTFOLIO_INPUT")
    odds = forecast.average_win_r / forecast.average_loss_r
    full_kelly = max(
        0.0,
        (odds * forecast.win_probability - (1.0 - forecast.win_probability)) / odds,
    )
    if full_kelly <= 0.0:
        return SizeDecision(0.0, 0.0, 0.0, (), "NON_POSITIVE_KELLY")
    confidence = (
        _clip(constraints.reliability)
        * _clip(constraints.observability)
        * _clip(constraints.execution_probability)
        * _clip(constraints.market_confidence)
        * _clip(constraints.sector_confidence)
    )
    target = full_kelly * config.kelly_fraction * confidence
    caps: list[str] = []
    candidates = {
        "SINGLE_NAME_CAP": config.single_name_cap,
        "SECTOR_CAP": max(
            0.0,
            constraints.current_name_fraction
            + config.sector_cap
            - constraints.current_sector_fraction,
        ),
        "THEME_CAP": max(
            0.0,
            constraints.current_name_fraction
            + config.theme_cap
            - constraints.current_theme_fraction,
        ),
        "ADV_CAP": constraints.current_name_fraction
        + config.adv_participation_cap * constraints.adv_value / constraints.equity,
        "EDGE_CAPACITY": constraints.current_name_fraction
        + constraints.edge_capacity_fraction_adv
        * constraints.adv_value
        / constraints.equity,
        "CASH_CAP": constraints.current_name_fraction
        + constraints.cash
        / constraints.equity,
    }
    for name, cap in candidates.items():
        if target > cap:
            target = cap
            caps.append(name)
    if constraints.drawdown >= config.hard_drawdown:
        target = min(target, constraints.current_name_fraction)
        caps.append("HARD_DRAWDOWN_NO_NEW_RISK")
    elif constraints.drawdown >= config.soft_drawdown:
        target *= config.extreme_gross_multiplier
        caps.append("SOFT_DRAWDOWN_MULTIPLIER")
    target = max(0.0, target)
    incremental = max(
        0.0,
        (target - constraints.current_name_fraction) * constraints.equity,
    )
    if (
        config.min_order_notional > 0
        and constraints.equity > 0.0
        and incremental > 0.0
        and incremental < config.min_order_notional
    ):
        required_fraction = config.min_order_notional / constraints.equity
        target = min(1.0, constraints.current_name_fraction + required_fraction)
        caps.append("MIN_ORDER_NOTIONAL_FLOOR")
        incremental = max(
            0.0,
            (target - constraints.current_name_fraction) * constraints.equity,
        )
    return SizeDecision(
        target_fraction=target,
        incremental_value=incremental,
        unconstrained_kelly=full_kelly,
        applied_caps=tuple(caps),
    )
