from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest

from cyq_game.domain import FutureDataError
from cyq_game.strategy.markup_retest import (
    freeze_lifecycle_anchor,
    load_markup_retest_config,
)
from cyq_game.strategy.signals import (
    _SIGNAL_INPUT_COLUMNS,
    generate_signal_events,
    observation_from_record,
)

CN_TZ = timezone(timedelta(hours=8))


def _row(
    symbol: str,
    day: date,
    *,
    setup_score: float = 0.8,
    breakout_excess_atr: float = 0.0,
    distribution_score: float = 0.0,
    volume: float = 50.0,
    turnover: float = 0.05,
    market_state: str = "RISK_ON",
    sector_state: str = "STRONG",
    is_evaluation_row: bool = True,
    hard_valid: bool = True,
    tradable: bool = True,
) -> dict[str, Any]:
    decision_at = datetime.combine(day, time(15, 30), CN_TZ)
    return {
        "symbol": symbol,
        "trade_date": day,
        "decision_at": decision_at,
        "available_at": decision_at,
        "daily_snapshot_id": f"daily-{day}",
        "feature_daily_snapshot_id": f"chip-{day}",
        "feature_minute_snapshot_id": f"minute-{day}",
        "research_hard_valid": hard_valid,
        "strict_hard_valid": False,
        "tradable_state": tradable,
        "history_count": 60,
        "setup_score": setup_score,
        "breakout_excess_atr": breakout_excess_atr,
        "support_regained": True,
        "chip_histogram_prices": [9.5, 9.8, 10.2],
        "chip_histogram_masses": [0.2, 0.6, 0.2],
        "cost_p10": 9.5,
        "cost_p90": 10.2,
        "state_quality": 1.0,
        "known_cost_fraction_min": 1.0,
        "model_spread_cost_p50": 0.0,
        "model_spread_cost_p90": 0.0,
        "model_spread_dominant_peak_today": 0.0,
        "peak_track_id": "peak-track-test",
        "peak_track_band_lower": 9.5,
        "peak_track_band_upper": 10.2,
        "peak_track_ambiguous": False,
        "peak_definition_version": "canonical-chip-peak-v1",
        "peak_count": 1,
        "recent_band_overlap": 0.9,
        "distribution_score": distribution_score,
        "structure_support": 10.0,
        "close": 10.2,
        "low": 9.9,
        "volume": volume,
        "turnover_fraction": turnover,
        "average_cost": 9.8,
        "cost_p50": 9.8,
        "prior_average_cost": 9.5,
        "prior_cost_p50": 9.5,
        "atr": 1.0,
        "structure_broken": False,
        "corporate_action_blocking": False,
        "market_state": market_state,
        "sector_state": sector_state,
        "effective_industry_pit_grade": "B_RESEARCH_ONLY",
        "sector_fallback": "INDUSTRY_LOO",
        "reason_codes": "",
        "ev_turnover_absorption": True,
        "ev_near_price_chip_growth": True,
        "ev_concentration_improves": True,
        "ev_sticky_base": True,
        "ev_downside_absorption": True,
        "dist_base_loss": None,
        "exact_lineage_state": "UNKNOWN",
        "dist_cost_band_expands": distribution_score >= 0.6,
        "dist_peak_splits": distribution_score >= 0.6,
        "dist_high_turnover_weak_impact": distribution_score >= 0.6,
        "dist_relative_reversal": distribution_score >= 0.6,
        "is_evaluation_row": is_evaluation_row,
    }


def _add_anchor_lineage(
    rows: list[dict[str, Any]],
    *,
    panel_snapshot_id: str = "panel-in-memory",
) -> list[dict[str, Any]]:
    config = load_markup_retest_config()
    observation = observation_from_record(rows[0], config, panel_snapshot_id)
    anchor = freeze_lifecycle_anchor(
        observation, strategy_version=config.strategy_version
    )
    for row in rows[1:]:
        row["anchor_retention_estimates"] = [
            {
                "anchor_id": anchor.anchor_id,
                "symbol": anchor.symbol,
                "anchor_date": anchor.created_at.isoformat(),
                "current_date": str(row["trade_date"]),
                "model_retentions": {
                    "UNIFORM": 0.8,
                    "DISPOSITION": 0.8,
                    "ACTIVE_STICKY": 0.8,
                },
                "ensemble_version": "test-v1",
            }
        ]
    return rows


def _complete_signal_rows(
    symbol: str, start: date, *, warmup: bool = False
) -> list[dict[str, Any]]:
    rows = [
        _row(symbol, start, is_evaluation_row=not warmup),
        _row(
            symbol,
            start + timedelta(days=1),
            breakout_excess_atr=0.3,
            volume=100.0,
            turnover=0.1,
            is_evaluation_row=not warmup,
        ),
        _row(symbol, start + timedelta(days=2), is_evaluation_row=True),
    ]
    return _add_anchor_lineage(rows)


def test_generator_rejects_future_label_columns() -> None:
    config = load_markup_retest_config()
    records = _complete_signal_rows("000001.SZ", date(2020, 6, 15))
    records[0]["return_20d"] = 0.99

    with pytest.raises(FutureDataError, match="return_20d"):
        generate_signal_events(records, config)


def test_generator_emits_every_threshold_qualified_signal_without_top_n() -> None:
    config = load_markup_retest_config()
    records = [
        row
        for index in range(30)
        for row in _complete_signal_rows(f"{index + 1:06d}.SZ", date(2020, 6, 15))
    ]

    generated = generate_signal_events(records, config)

    assert len(generated.signals) == 30
    assert generated.evaluation_signal_rows == 30
    assert {row["symbol"] for row in generated.signals} == {
        f"{index + 1:06d}.SZ" for index in range(30)
    }


def test_warmup_state_is_used_but_only_evaluation_signal_is_counted() -> None:
    config = load_markup_retest_config()
    records = _complete_signal_rows("000001.SZ", date(2020, 6, 13), warmup=True)

    generated = generate_signal_events(records, config)

    assert generated.evaluation_rows == 1
    assert generated.evaluation_signal_rows == 1
    signal = generated.signals[0]
    assert signal["accumulation_started_at"] == "2020-06-13"
    assert signal["breakout_at"] == "2020-06-14"
    assert signal["retest_confirmed_at"] == "2020-06-15"
    assert signal["is_evaluation_row"] is True


def test_unknown_sector_prevents_signal_instead_of_granting_confidence() -> None:
    config = load_markup_retest_config()
    records = _complete_signal_rows("000001.SZ", date(2020, 6, 15))
    records[-1]["sector_state"] = "UNKNOWN"

    generated = generate_signal_events(records, config)

    assert generated.signals == ()


def test_chip_model_disagreement_and_p90_overhang_remain_visible_evidence() -> None:
    config = load_markup_retest_config()
    row = _row("000001.SZ", date(2020, 6, 15))
    row.update(
        {
            "close": 10.0,
            "cost_p90": 10.5,
            "state_quality": 0.1,
            "known_cost_fraction_min": 0.8,
            "model_spread_cost_p50": 0.5,
            "model_spread_cost_p90": 2.0,
            "model_spread_dominant_peak_today": 1.0,
            "atr": 1.0,
        }
    )

    observation = observation_from_record(row, config, "panel-1")

    assert "known_cost_fraction=0.800000" in observation.alternative_explanations
    assert "chip_model_disagreement_atr=2.000000" in observation.alternative_explanations
    assert "chip_observability_score=0.266667" in observation.alternative_explanations
    assert "global_p90_overhang_atr=0.500000" in observation.alternative_explanations
    assert observation.chip_model_disagreement_atr == pytest.approx(2.0)


def test_missing_model_disagreement_fails_closed() -> None:
    config = load_markup_retest_config()
    row = _row("000001.SZ", date(2020, 6, 15))
    row["known_cost_fraction_min"] = 0.8
    row.pop("model_spread_cost_p50")
    row.pop("model_spread_cost_p90")
    row.pop("model_spread_dominant_peak_today")

    observation = observation_from_record(row, config, "panel-1")

    assert observation.chip_model_disagreement_atr == 1.0e12
    assert "chip_model_disagreement=UNKNOWN" in observation.alternative_explanations


def test_stream_projection_keeps_intraday_support_evidence() -> None:
    assert "close_vs_vwap" in _SIGNAL_INPUT_COLUMNS


def test_distribution_exit_stays_pending_until_execution_confirms_fill() -> None:
    config = load_markup_retest_config()
    start = date(2020, 6, 1)
    records = _complete_signal_rows("000001.SZ", start)
    records.extend(
        (
            _row("000001.SZ", start + timedelta(days=3), distribution_score=0.8),
            _row("000001.SZ", start + timedelta(days=4), distribution_score=0.8),
        )
    )
    for offset in range(5, 25):
        records.append(_row("000001.SZ", start + timedelta(days=offset)))
    records.append(_row("000001.SZ", start + timedelta(days=25)))
    _add_anchor_lineage(records)

    generated = generate_signal_events(records, config)

    event_types = [row["event_type"] for row in generated.events]
    assert event_types.count("SIGNAL_CREATED") == 1
    assert event_types.count("EXIT_INTENT") == 1
    assert event_types.count("COOLDOWN_STARTED") == 0
    assert event_types.count("SIGNAL_CREATED") == 1


def test_soft_distribution_exit_is_cancelled_after_recovery() -> None:
    config = load_markup_retest_config()
    start = date(2020, 6, 1)
    records = _complete_signal_rows("000001.SZ", start)
    records.extend(
        (
            _row("000001.SZ", start + timedelta(days=3), distribution_score=0.8),
            _row("000001.SZ", start + timedelta(days=4), distribution_score=0.2),
        )
    )
    _add_anchor_lineage(records)

    generated = generate_signal_events(records, config)

    event_types = [row["event_type"] for row in generated.events]
    assert "SOFT_EXIT_CANCELLED" in event_types
    assert "EXIT_INTENT" not in event_types


@pytest.mark.parametrize(
    "records",
    (
        [
            _row("000001.SZ", date(2020, 6, 16)),
            _row("000001.SZ", date(2020, 6, 15)),
        ],
        [
            _row("000001.SZ", date(2020, 6, 15)),
            _row("000001.SZ", date(2020, 6, 15)),
        ],
    ),
)
def test_generator_rejects_unsorted_or_duplicate_state_input(
    records: list[dict[str, Any]],
) -> None:
    config = load_markup_retest_config()

    with pytest.raises(ValueError, match="unique and ordered"):
        generate_signal_events(records, config)
