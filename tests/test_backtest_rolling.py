from __future__ import annotations

from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from cyq_game.backtest.engine import BacktestEngine, _rolling_stats, _RollingStatsTracker
from cyq_game.chip import CohortChipEngine
from cyq_game.domain import Bar


def test_incremental_rolling_stats_match_reference_scan() -> None:
    tracker = _RollingStatsTracker()
    history: list[Bar] = []
    start = date(2022, 1, 1)

    for index in range(700):
        close = 10.0 + index * 0.003 + (index % 17) * 0.011
        bar = Bar(
            symbol="000001.SZ",
            trade_date=start + timedelta(days=index),
            open=close * 0.998,
            high=close * 1.012,
            low=close * 0.988,
            close=close,
            volume=1_000_000.0 + (index % 23) * 31_337.0,
            amount=close * (1_000_000.0 + (index % 23) * 31_337.0),
            free_float_shares=100_000_000.0,
            available_at=datetime.combine(
                start + timedelta(days=index),
                datetime.min.time(),
                tzinfo=UTC,
            ),
        )
        history.append(bar)
        actual = tracker.update(bar)
        expected = _rolling_stats(history)
        for field in fields(actual):
            assert getattr(actual, field.name) == pytest.approx(
                getattr(expected, field.name), rel=1e-12, abs=1e-12
            )


def test_first_chip_observation_has_no_same_bar_pretrade_signal() -> None:
    engine = object.__new__(BacktestEngine)
    engine.config = SimpleNamespace(
        chip=SimpleNamespace(
            grid_step_pct=0.01,
            smoothing_sigma_bins=1.5,
            peak_prominence=0.03,
        )
    )
    engine._chip_engine = CohortChipEngine()
    engine._chip_states = {}
    engine._base_bands = {}
    bar = Bar(
        symbol="000001.SZ",
        trade_date=date(2024, 1, 2),
        open=9.9,
        high=10.2,
        low=9.8,
        close=10.1,
        volume=1_000_000.0,
        amount=10_050_000.0,
        free_float_shares=100_000_000.0,
        available_at=datetime(2024, 1, 2, tzinfo=UTC),
    )
    stats = _RollingStatsTracker().update(bar)

    features = engine._update_chip(bar.symbol, bar, stats)

    assert features.quality == 0.0
    assert features.cyqk_pre.open == features.cyqk_pre.high == 0.0
    assert features.cyqk_pre.low == features.cyqk_pre.close == 0.0
    assert "PRETRADE_CHIP_STATE_UNAVAILABLE" in features.priors
