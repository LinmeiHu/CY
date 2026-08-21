from __future__ import annotations

from dataclasses import dataclass, replace

from cyq_game.data import ChipObservation
from cyq_game.domain import Bar

from .core import ChipEngine, ChipState, FloatArray, LogPriceGrid, ensure_grid
from .features import CYQK, ChipFeatures, compute_cyqk, compute_features


@dataclass(frozen=True)
class ChipTransition:
    """One causal bar transition shared by replay and batch precomputation."""

    state: ChipState
    features: ChipFeatures | None
    initial_base_band: tuple[float, float, float] | None = None


def advance_chip_state(
    engine: ChipEngine,
    previous: ChipState | None,
    bar: Bar,
    observation: ChipObservation | None = None,
    *,
    grid_step_pct: float = 0.01,
    history_low_2y: float | None = None,
    history_high_2y: float | None = None,
    smoothing_sigma: float = 1.5,
    peak_prominence: float = 0.03,
    with_features: bool = True,
) -> ChipTransition:
    """Advance exactly once; same-bar observations only affect the post state."""

    observed_low, observed_high = observation_bounds(observation, bar)
    if previous is None:
        grid = LogPriceGrid.around(observed_low, observed_high, grid_step_pct)
        q = volume_distribution(grid, bar, observation)
        state = engine.initialize(grid, q, bar.trade_date)
        p10, p90 = state.quantile(0.10), state.quantile(0.90)
        in_base = (state.grid.prices >= p10) & (state.grid.prices <= p90)
        base_band = (p10, p90, float(state.mass[in_base].sum()))
        if not with_features:
            return ChipTransition(state, None, base_band)
        post = compute_features(
            state,
            open_price=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        features = replace(
            post,
            cyqk_pre=CYQK(open=0.0, high=0.0, low=0.0, close=0.0),
            priors=(*post.priors, "PRETRADE_CHIP_STATE_UNAVAILABLE"),
            quality=0.0,
        )
        return ChipTransition(state, features, base_band)

    state = ensure_grid(previous, observed_low, observed_high)
    cyqk_pre = None
    if with_features:
        cyqk_pre = compute_cyqk(
            state,
            open_price=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
    q = volume_distribution(state.grid, bar, observation)
    updated = engine.update(
        state,
        q,
        bar.turnover,
        bar.close,
        bar.trade_date,
        suspended=bar.suspended,
    )
    if not with_features:
        return ChipTransition(updated, None)
    post = compute_features(
        updated,
        open_price=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        history_low_2y=history_low_2y,
        history_high_2y=history_high_2y,
        smoothing_sigma=smoothing_sigma,
        peak_prominence=peak_prominence,
    )
    if cyqk_pre is None:  # pragma: no cover - narrowed by with_features above
        raise AssertionError("pre-trade CYQK must be present")
    return ChipTransition(updated, replace(post, cyqk_pre=cyqk_pre))


def observation_bounds(
    observation: ChipObservation | None,
    bar: Bar,
) -> tuple[float, float]:
    if observation is None or not observation.hard_valid:
        return bar.low, bar.high
    return min(bar.low, min(observation.prices)), max(bar.high, max(observation.prices))


def volume_distribution(
    grid: LogPriceGrid,
    bar: Bar,
    observation: ChipObservation | None,
) -> FloatArray:
    if observation is not None and observation.hard_valid:
        return grid.observed_volume_at_price(observation.prices, observation.volumes)
    return grid.volume_at_price(bar.low, bar.high, bar.close)
