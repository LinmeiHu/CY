"""Pure, causal logic for the survivor-biased ChinNext V1 smoke baseline.

This module deliberately does not import or mutate the frozen SuperMind V6
strategy.  Every price/volume sequence passed to a signal function ends at the
completed signal session.  Execution is modeled separately at a later open.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
from statistics import fmean, median
from typing import Any


RESEARCH_MODE = "EXPLORATORY_SURVIVOR_BIASED"
MARKET_ANCHOR = "399102.SZ"
BREAKOUT_VOLUME_MODE = "SHADOW"
RANK_REPLACEMENT = "OFF"
EXECUTION_LIMIT_MODEL = "PARTIAL"


@dataclass(frozen=True)
class ChinNextV1Config:
    breakout_days: int = 60
    entry_ma: int = 20
    box_days: int = 40
    box_width_max: float = 0.20
    ma_dispersion_max: float = 0.08
    direction_efficiency_max: float = 0.45
    vol_ratio_max: float = 0.85
    minvol_lookback: int = 30
    minvol_location_max: float = 0.50
    minvol_ratio_max: float = 0.70
    breakout_volume_lookback: int = 20
    breakout_volume_threshold: float = 1.20
    exit_ma: int = 30
    exit_confirm: int = 2
    market_ma: int = 20
    market_exit_confirm: int = 2
    market_emergency_ratio: float = 0.96
    rs20_weight: float = 0.20
    rs60_weight: float = 0.50
    rs120_weight: float = 0.30
    max_holdings: int = 10
    target_weight: float = 0.10
    turnover20_days: int = 20
    turnover20_min_cny: float = 100_000_000.0
    min_completed_observations: int = 180
    transaction_cost_bps: float = 10.0

    def __post_init__(self) -> None:
        positive_ints = (
            self.breakout_days,
            self.entry_ma,
            self.box_days,
            self.minvol_lookback,
            self.breakout_volume_lookback,
            self.exit_ma,
            self.exit_confirm,
            self.market_ma,
            self.market_exit_confirm,
            self.max_holdings,
            self.turnover20_days,
            self.min_completed_observations,
        )
        if any(value <= 0 for value in positive_ints):
            raise ValueError("all configured window/count values must be positive")
        if abs(self.rs20_weight + self.rs60_weight + self.rs120_weight - 1.0) > 1e-12:
            raise ValueError("RS weights must sum exactly to one")
        if not (0 < self.target_weight <= 1):
            raise ValueError("target_weight must be in (0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Full40Diagnostic:
    valid: bool
    passed: bool
    box_width: float | None
    ma_dispersion: float | None
    direction_efficiency: float | None
    vol_ratio: float | None
    reason: str


@dataclass(frozen=True)
class MinVolDiagnostic:
    valid: bool
    passed: bool
    location_passed: bool
    ratio_passed: bool
    location: float | None
    minimum_volume: float | None
    average_volume: float | None
    minimum_volume_ratio: float | None
    reason: str


@dataclass(frozen=True)
class BreakoutVolumeDiagnostic:
    valid: bool
    passed: bool
    ratio: float | None
    denominator: float | None
    reason: str


@dataclass(frozen=True)
class FillDecision:
    filled: bool
    price: float | None
    reason: str
    t1_status: str


def _finite_positive(values: Sequence[float]) -> bool:
    return bool(values) and all(isfinite(float(value)) and float(value) > 0 for value in values)


def strict_breakout(closes: Sequence[float], breakout_days: int) -> bool:
    """Return true only when t close strictly exceeds t-N..t-1 closes."""

    if breakout_days <= 0 or len(closes) < breakout_days + 1:
        return False
    window = list(closes[-(breakout_days + 1) : -1])
    signal_close = float(closes[-1])
    return _finite_positive(window) and isfinite(signal_close) and signal_close > max(window)


def close_above_ma(closes: Sequence[float], window: int) -> bool:
    if window <= 0 or len(closes) < window:
        return False
    tail = list(closes[-window:])
    return _finite_positive(tail) and float(closes[-1]) > fmean(tail)


def full40_diagnostic(
    closes: Sequence[float], config: ChinNextV1Config
) -> Full40Diagnostic:
    """Evaluate FULL40 using prior sessions only, excluding signal day t."""

    prior = list(closes[:-1])
    required = max(config.box_days, 61, 30)
    if len(prior) < required:
        return Full40Diagnostic(False, False, None, None, None, None, "INSUFFICIENT_HISTORY")
    box = prior[-config.box_days :]
    if not _finite_positive(box) or not _finite_positive(prior[-61:]):
        return Full40Diagnostic(False, False, None, None, None, None, "NONFINITE_OR_NONPOSITIVE")

    low = min(box)
    box_width = max(box) / low - 1.0
    mas = [fmean(prior[-days:]) for days in (5, 10, 20, 30)]
    ma_dispersion = max(mas) / min(mas) - 1.0
    path = sum(abs(right - left) for left, right in zip(box, box[1:], strict=False))
    direction_efficiency = 0.0 if path == 0 else abs(box[-1] - box[0]) / path
    returns = [right / left - 1.0 for left, right in zip(prior, prior[1:], strict=False)]
    ret10 = returns[-10:]
    ret60 = returns[-60:]
    vol10 = _sample_std(ret10)
    vol60 = _sample_std(ret60)
    if vol10 is None or vol60 is None or vol60 <= 0:
        return Full40Diagnostic(
            False,
            False,
            box_width,
            ma_dispersion,
            direction_efficiency,
            None,
            "INVALID_VOLATILITY",
        )
    vol_ratio = vol10 / vol60
    checks = (
        (box_width <= config.box_width_max, "BOX_WIDTH"),
        (ma_dispersion <= config.ma_dispersion_max, "MA_DISPERSION"),
        (direction_efficiency <= config.direction_efficiency_max, "DIRECTION_EFFICIENCY"),
        (vol_ratio <= config.vol_ratio_max, "VOL_RATIO"),
    )
    failed = [name for passed, name in checks if not passed]
    return Full40Diagnostic(
        True,
        not failed,
        box_width,
        ma_dispersion,
        direction_efficiency,
        vol_ratio,
        "PASS" if not failed else "+".join(failed),
    )


def _sample_std(values: Sequence[float]) -> float | None:
    if len(values) < 2 or not all(isfinite(float(value)) for value in values):
        return None
    center = fmean(values)
    return (sum((float(value) - center) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def entry_price_structure(
    closes: Sequence[float], config: ChinNextV1Config
) -> tuple[bool, Full40Diagnostic]:
    full = full40_diagnostic(closes, config)
    passed = (
        strict_breakout(closes, config.breakout_days)
        and close_above_ma(closes, config.entry_ma)
        and full.passed
    )
    return passed, full


def minvol_diagnostic(
    closes: Sequence[float], volumes: Sequence[float], config: ChinNextV1Config
) -> MinVolDiagnostic:
    """Evaluate t-lookback..t-1 only; signal volume is never consumed."""

    common = min(len(closes), len(volumes))
    lookback = config.minvol_lookback
    if common < lookback + 1:
        return MinVolDiagnostic(False, False, False, False, None, None, None, None, "INSUFFICIENT_HISTORY")
    aligned_close = list(closes[-common:])
    aligned_volume = list(volumes[-common:])
    prior_close = aligned_close[-(lookback + 1) : -1]
    prior_volume = aligned_volume[-(lookback + 1) : -1]
    if not _finite_positive(prior_close) or not _finite_positive(prior_volume):
        return MinVolDiagnostic(False, False, False, False, None, None, None, None, "NONFINITE_OR_NONPOSITIVE")
    minimum_index = min(range(lookback), key=lambda index: prior_volume[index])
    minimum_volume = float(prior_volume[minimum_index])
    average_volume = fmean(prior_volume)
    low = min(prior_close)
    high = max(prior_close)
    location = 0.0 if high <= low else (prior_close[minimum_index] - low) / (high - low)
    ratio = minimum_volume / average_volume
    location_passed = location <= config.minvol_location_max
    ratio_passed = ratio <= config.minvol_ratio_max
    passed = location_passed and ratio_passed
    return MinVolDiagnostic(
        True,
        passed,
        location_passed,
        ratio_passed,
        location,
        minimum_volume,
        average_volume,
        ratio,
        "PASS" if passed else "+".join(
            name
            for okay, name in (
                (location_passed, "LOCATION"),
                (ratio_passed, "MINIMUM_VOLUME_RATIO"),
            )
            if not okay
        ),
    )


def breakout_volume_diagnostic(
    volumes: Sequence[float], config: ChinNextV1Config
) -> BreakoutVolumeDiagnostic:
    lookback = config.breakout_volume_lookback
    if len(volumes) < lookback + 1:
        return BreakoutVolumeDiagnostic(False, False, None, None, "INSUFFICIENT_HISTORY")
    prior = list(volumes[-(lookback + 1) : -1])
    signal = float(volumes[-1])
    if not _finite_positive(prior) or not isfinite(signal) or signal <= 0:
        return BreakoutVolumeDiagnostic(False, False, None, None, "NONFINITE_OR_NONPOSITIVE")
    denominator = fmean(prior)
    ratio = signal / denominator
    passed = ratio >= config.breakout_volume_threshold
    return BreakoutVolumeDiagnostic(True, passed, ratio, denominator, "PASS" if passed else "BELOW_THRESHOLD")


def own_exit_signal(closes: Sequence[float], config: ChinNextV1Config) -> bool:
    """Config-driven MA exit requiring each of the last confirmation closes below its own MA."""

    required = config.exit_ma + config.exit_confirm - 1
    if len(closes) < required:
        return False
    for offset in range(config.exit_confirm):
        end = len(closes) - offset
        window = list(closes[end - config.exit_ma : end])
        if not _finite_positive(window) or not float(closes[end - 1]) < fmean(window):
            return False
    return True


def market_gate_state(
    closes: Sequence[float], config: ChinNextV1Config
) -> dict[str, bool]:
    if len(closes) < config.market_ma + config.market_exit_confirm - 1:
        return {"valid": False, "entry_permission": False, "normal_exit": False, "emergency_exit": False}
    entry = close_above_ma(closes, config.market_ma)
    below = []
    for offset in range(config.market_exit_confirm):
        end = len(closes) - offset
        window = list(closes[end - config.market_ma : end])
        if not _finite_positive(window):
            return {"valid": False, "entry_permission": False, "normal_exit": False, "emergency_exit": False}
        below.append(float(closes[end - 1]) < fmean(window))
    current_window = list(closes[-config.market_ma :])
    emergency = float(closes[-1]) < fmean(current_window) * config.market_emergency_ratio
    return {"valid": True, "entry_permission": entry, "normal_exit": all(below), "emergency_exit": emergency}


def momentum_values(closes: Sequence[float]) -> tuple[float, float, float] | None:
    if len(closes) < 121 or not _finite_positive(closes[-121:]):
        return None
    price = float(closes[-1])
    return (price / closes[-21] - 1.0, price / closes[-61] - 1.0, price / closes[-121] - 1.0)


def _average_percentile(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted((float(value), symbol) for symbol, value in values.items())
    result: dict[str, float] = {}
    index = 0
    count = len(ordered)
    while index < count:
        stop = index + 1
        while stop < count and ordered[stop][0] == ordered[index][0]:
            stop += 1
        average_rank = ((index + 1) + stop) / 2.0
        percentile = average_rank / count
        for _, symbol in ordered[index:stop]:
            result[symbol] = percentile
        index = stop
    return result


def build_rs_table(
    histories: Mapping[str, Sequence[float]],
    eligible_symbols: Iterable[str],
    config: ChinNextV1Config,
) -> dict[str, dict[str, float]]:
    """Rank the full basic-eligible cross section, never only breakouts."""

    momenta: dict[str, tuple[float, float, float]] = {}
    for symbol in sorted(set(eligible_symbols)):
        values = momentum_values(histories.get(symbol, ()))
        if values is not None:
            momenta[symbol] = values
    if not momenta:
        return {}
    r20 = _average_percentile({symbol: values[0] for symbol, values in momenta.items()})
    r60 = _average_percentile({symbol: values[1] for symbol, values in momenta.items()})
    r120 = _average_percentile({symbol: values[2] for symbol, values in momenta.items()})
    rows: dict[str, dict[str, float]] = {}
    for symbol, values in momenta.items():
        rows[symbol] = {
            "mom20": values[0],
            "mom60": values[1],
            "mom120": values[2],
            "r20": r20[symbol],
            "r60": r60[symbol],
            "r120": r120[symbol],
            "score": (
                config.rs20_weight * r20[symbol]
                + config.rs60_weight * r60[symbol]
                + config.rs120_weight * r120[symbol]
            ),
        }
    return rows


def sort_candidates(candidates: Iterable[str], rs: Mapping[str, Mapping[str, float]]) -> list[str]:
    return sorted(
        (symbol for symbol in set(candidates) if symbol in rs),
        key=lambda symbol: (-float(rs[symbol]["score"]), -float(rs[symbol]["mom60"]), symbol),
    )


def select_no_replacement_members(
    current_members: Iterable[str],
    forced_exits: Iterable[str],
    ranked_candidates: Sequence[str],
    config: ChinNextV1Config,
) -> tuple[str, ...]:
    forced = set(forced_exits)
    survivors = sorted(set(current_members) - forced)
    vacancies = max(0, config.max_holdings - len(survivors))
    additions = [symbol for symbol in ranked_candidates if symbol not in survivors and symbol not in forced][:vacancies]
    return tuple(sorted(survivors + additions))


def desired_target_weights(members: Iterable[str], config: ChinNextV1Config) -> dict[str, float]:
    selected = sorted(set(members))
    if len(selected) > config.max_holdings:
        raise ValueError("desired member set exceeds max holdings")
    return {symbol: config.target_weight for symbol in selected}


def set_change_required(previous: Iterable[str], desired: Iterable[str]) -> bool:
    return set(previous) != set(desired)


def can_sell(acquisition_date: date, execution_date: date) -> bool:
    return execution_date > acquisition_date


def decide_next_open_fill(
    *,
    signal_date: date,
    execution_date: date,
    side: str,
    row: Mapping[str, Any] | None,
    acquisition_date: date | None = None,
) -> FillDecision:
    """Fail-closed next-session open decision with minimal T+1 and limit gates."""

    normalized_side = side.upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if execution_date <= signal_date:
        return FillDecision(False, None, "NOT_AFTER_SIGNAL_DATE", "NOT_APPLICABLE")
    if normalized_side == "SELL" and acquisition_date is not None and not can_sell(acquisition_date, execution_date):
        return FillDecision(False, None, "T1_BLOCKED", "BLOCKED")
    if row is None:
        return FillDecision(False, None, "MISSING_DAILY_ROW", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")
    open_price = row.get("open")
    if open_price is None or not isfinite(float(open_price)) or float(open_price) <= 0:
        return FillDecision(False, None, "INVALID_OPEN", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")
    if row.get("hard_valid") is not True:
        return FillDecision(False, None, "HARD_INVALID", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")
    if row.get("trade_status") != 1 or row.get("current_day_data_tradable") is not True:
        return FillDecision(False, None, "NOT_TRADABLE", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")
    blocked_field = "buy_blocked_open" if normalized_side == "BUY" else "sell_blocked_open"
    if row.get(blocked_field) is not False:
        return FillDecision(False, None, "OPEN_LIMIT_BLOCKED_OR_UNKNOWN", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")
    return FillDecision(True, float(open_price), "FILLED", "PASS" if normalized_side == "SELL" else "NOT_APPLICABLE")


def deterministic_equidistant_sample(symbols: Sequence[str], size: int) -> tuple[str, ...]:
    ordered = sorted(set(symbols))
    if size <= 0:
        raise ValueError("sample size must be positive")
    if len(ordered) <= size:
        return tuple(ordered)
    indices = [round(index * (len(ordered) - 1) / (size - 1)) for index in range(size)]
    return tuple(ordered[index] for index in indices)


def performance_summary(nav: Sequence[float], sessions_per_year: int = 244) -> dict[str, float]:
    if len(nav) < 2 or not _finite_positive(nav):
        raise ValueError("NAV series must contain at least two finite positive values")
    total_return = float(nav[-1]) / float(nav[0]) - 1.0
    annualized = (float(nav[-1]) / float(nav[0])) ** (sessions_per_year / (len(nav) - 1)) - 1.0
    peak = float(nav[0])
    max_drawdown = 0.0
    for value in nav:
        peak = max(peak, float(value))
        max_drawdown = min(max_drawdown, float(value) / peak - 1.0)
    return {"total_return": total_return, "annualized_return": annualized, "max_drawdown": max_drawdown}


def trade_return_summary(returns: Sequence[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in returns if isfinite(float(value))]
    if not finite:
        return {"trade_count": 0, "win_rate": None, "average_trade_return": None, "median_trade_return": None}
    return {
        "trade_count": len(finite),
        "win_rate": sum(value > 0 for value in finite) / len(finite),
        "average_trade_return": fmean(finite),
        "median_trade_return": median(finite),
    }
