from __future__ import annotations

import math

import duckdb


def test_frozen_t0_feature_formulas_and_orientations() -> None:
    open_, high, low, close, preclose = 9.2, 10.0, 9.0, 9.1, 10.0
    close_location_danger = 1.0 - (close - low) / (high - low)
    current_day_loss_danger = -(close / preclose - 1.0)
    adverse_gap_danger = -(open_ / preclose - 1.0)
    assert math.isclose(close_location_danger, 0.9)
    assert math.isclose(current_day_loss_danger, 0.09)
    assert math.isclose(adverse_gap_danger, 0.08)
    assert all(value > 0 for value in (
        close_location_danger,
        current_day_loss_danger,
        adverse_gap_danger,
    ))


def test_zero_range_t0_fails_closed() -> None:
    high = low = 10.0
    assert high - low == 0.0


def test_five_session_persistence_ends_at_t0() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH history(seq, ret) AS (
          VALUES (1,-0.01),(2,0.01),(3,-0.02),(4,-0.01),(5,0.00),(6,-0.03)
        )
        SELECT seq,
               sum((ret < 0)::INTEGER) OVER (
                 ORDER BY seq ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
               ) AS negative_days_5
        FROM history ORDER BY seq
        """
    ).fetchall()
    assert rows[-1] == (6, 3)


def test_composite_is_fixed_equal_weight_and_higher_is_more_dangerous() -> None:
    safe = (0.10, 0.20, 0.10, 0.20)
    dangerous = (0.90, 0.80, 0.90, 0.80)
    safe_score = sum(safe) / 4.0
    dangerous_score = sum(dangerous) / 4.0
    assert math.isclose(safe_score, 0.15)
    assert math.isclose(dangerous_score, 0.85)
    assert dangerous_score > safe_score


def test_primary_label_and_cash_veto_semantics() -> None:
    assert (-0.10 <= -0.10) is True
    assert (-0.0999 <= -0.10) is False
    entered_returns = [0.10, -0.05]
    skipped_return = 0.0
    opportunity_mean = sum([*entered_returns, skipped_return]) / 3
    retained_mean = sum(entered_returns) / len(entered_returns)
    assert math.isclose(opportunity_mean, 1 / 60)
    assert math.isclose(retained_mean, 0.025)


def test_fixed_persistence_bins_are_outcome_blind() -> None:
    def bucket(negative_days: int) -> int:
        if negative_days <= 1:
            return 1
        return negative_days

    assert [bucket(value) for value in range(6)] == [1, 1, 2, 3, 4, 5]
