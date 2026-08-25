from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from cyq_game.domain import FutureDataError
from cyq_game.strategy.chip_incremental import (
    assert_price_volume_candidate_schema,
    fixed_chip_primitives,
    select_price_volume_candidates,
)


def _row(day: date, session: int, **updates: object) -> dict[str, object]:
    decision = datetime.combine(day, datetime.min.time()).replace(hour=15, minute=30)
    value: dict[str, object] = {
        "symbol": "000001.SZ",
        "trade_date": day,
        "decision_at": decision,
        "available_at": decision - timedelta(minutes=1),
        "daily_snapshot_id": f"daily-{day.isoformat()}",
        "symbol_session_index": session,
        "research_hard_valid": True,
        "tradable_state": True,
        "support_regained_price": True,
        "prior_breakout_excess_atr": 0.25,
        "market_state": "NEUTRAL",
        "sector_state": "NEUTRAL",
    }
    value.update(updates)
    return value


def test_candidate_schema_rejects_old_chip_contaminated_fields() -> None:
    with pytest.raises(ValueError, match="breakout_excess_atr"):
        assert_price_volume_candidate_schema((*_row(date(2020, 1, 2), 1), "breakout_excess_atr"))
    with pytest.raises(ValueError, match="profit_ratio"):
        assert_price_volume_candidate_schema((*_row(date(2020, 1, 2), 1), "profit_ratio"))


def test_candidate_selection_applies_fixed_gates_and_twenty_session_cooldown() -> None:
    rows = [
        _row(date(2020, 1, 2), 60),
        _row(date(2020, 1, 9), 65),
        _row(date(2020, 2, 3), 80),
        _row(date(2020, 3, 2), 100, sector_state="WEAK"),
    ]
    selected = select_price_volume_candidates(rows)

    assert [row["trade_date"] for row in selected] == [
        date(2020, 1, 2),
        date(2020, 2, 3),
    ]
    assert all(row["candidate_uses_chip_fields"] is False for row in selected)
    assert all(str(row["candidate_id"]).startswith("pv-candidate-") for row in selected)


def test_candidate_selection_fails_closed_on_future_or_late_data() -> None:
    with pytest.raises(FutureDataError, match="outside development"):
        select_price_volume_candidates([_row(date(2023, 1, 3), 800)])
    late = _row(date(2022, 12, 30), 700)
    late["available_at"] = datetime(2022, 12, 30, 16, 0)
    with pytest.raises(FutureDataError, match="available after decision"):
        select_price_volume_candidates([late])


def test_candidate_threshold_and_cooldown_are_not_tunable() -> None:
    assert select_price_volume_candidates(
        [_row(date(2020, 1, 2), 60, prior_breakout_excess_atr=0.2499)]
    ) == []
    with pytest.raises(ValueError, match="fixes candidate cooldown"):
        select_price_volume_candidates([_row(date(2020, 1, 2), 60)], cooldown_sessions=19)


def test_fixed_chip_primitives_follow_preregistered_formulas() -> None:
    raw: dict[str, object] = {
        "semantic_research_valid": True,
        "exact_research_valid": True,
        "known_cost_fraction_min": 0.99,
        "close": 12.0,
        "atr14": 1.2,
        "momentum_20": 0.20,
        "close_lag20": 10.0,
        "atr14_lag20": 1.0,
        "momentum_20_lag20": 0.10,
        "exact_p50": 11.0,
        "exact_p50_lag20": 10.0,
        "exact_p50_lag40": 9.5,
        "dominant_band_mass": 0.40,
        "dominant_band_mass_lag20": 0.35,
        "i70_lower": 10.0,
        "i70_upper": 11.2,
        "i90_lower": 9.0,
        "i90_upper": 12.0,
        "i70_lower_lag20": 9.0,
        "i70_upper_lag20": 10.5,
        "i90_lower_lag20": 8.0,
        "i90_upper_lag20": 11.0,
        "i90_width_fraction": 0.25,
        "i90_width_fraction_lag20": 0.30,
        "i90_width_fraction_lag40": 0.35,
        "profit_ratio": 0.70,
        "profit_ratio_lag20": 0.60,
        "profit_ratio_lag40": 0.55,
        "lower_peak_strength": 0.20,
        "upper_peak_strength": 0.10,
        "valley_depth": 0.80,
        "lower_peak_strength_lag20": 0.20,
        "upper_peak_strength_lag20": 0.15,
        "valley_depth_lag20": 0.70,
        "model_spread_i90_width_fraction": 0.02,
    }
    result = fixed_chip_primitives(raw)

    assert result["chip_measurement_valid"] is True
    assert result["i70_width_atr"] == pytest.approx(1.0)
    assert result["i90_width_atr"] == pytest.approx(2.5)
    assert result["price_minus_cost_migration_20_vol"] == pytest.approx(1.0)
    assert result["profit_ratio_change_20"] == pytest.approx(0.10)
    assert result["i90_contraction_20"] == pytest.approx(0.05)
    assert result["upper_to_lower_peak_strength"] == pytest.approx(0.5)
    assert result["seller_model_disagreement_atr"] == pytest.approx(0.2)
    assert result["stale_profit_ratio_change_20"] == pytest.approx(0.05)
