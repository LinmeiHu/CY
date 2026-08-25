from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pytest

from cyq_game.domain import FutureDataError
from cyq_game.strategy.markup_retest import (
    freeze_lifecycle_anchor,
    load_markup_retest_config,
)
from cyq_game.strategy.research import (
    _merge_entry_lattice_results,
    entry_parameter_grid,
    exit_parameter_grid,
    screen_entry_lattice,
)
from cyq_game.strategy.signals import generate_signal_events, observation_from_record

CN_TZ = timezone(timedelta(hours=8))


def _row(symbol: str, day: date, *, breakout: float = 0.0) -> dict[str, Any]:
    decision_at = datetime.combine(day, time(15, 30), CN_TZ)
    is_breakout = breakout > 0
    return {
        "symbol": symbol,
        "trade_date": day,
        "decision_at": decision_at,
        "available_at": decision_at,
        "daily_snapshot_id": f"daily-{day}",
        "feature_daily_snapshot_id": f"chip-{day}",
        "feature_minute_snapshot_id": f"minute-{day}",
        "research_hard_valid": True,
        "strict_hard_valid": False,
        "tradable_state": True,
        "history_count": 60,
        "setup_score": 0.8,
        "breakout_excess_atr": breakout,
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
        "peak_definition_version": "canonical-chip-peak-v2",
        "peak_count": 1,
        "recent_band_overlap": 0.9,
        "distribution_score": 0.0,
        "structure_support": 10.0,
        "close": 10.2,
        "low": 9.9,
        "volume": 100.0 if is_breakout else 50.0,
        "turnover_fraction": 0.1 if is_breakout else 0.05,
        "average_cost": 9.8,
        "cost_p50": 9.8,
        "prior_average_cost": 9.5,
        "prior_cost_p50": 9.5,
        "atr": 1.0,
        "structure_broken": False,
        "corporate_action_blocking": False,
        "corporate_action_ids": "",
        "market_state": "RISK_ON",
        "sector_state": "STRONG",
        "effective_industry_pit_grade": "B_RESEARCH_ONLY",
        "sector_fallback": "INDUSTRY_LOO",
        "reason_codes": "",
        "ev_turnover_absorption": True,
        "ev_near_price_chip_growth": True,
        "ev_concentration_improves": True,
        "ev_sticky_base": True,
        "ev_downside_absorption": True,
        "dist_base_loss": False,
        "dist_cost_band_expands": False,
        "dist_peak_splits": False,
        "dist_high_turnover_weak_impact": False,
        "dist_relative_reversal": False,
        "is_evaluation_row": True,
    }


def _complete_signal_rows(
    symbol: str,
    start: date,
    *,
    panel_snapshot_id: str = "panel-in-memory",
) -> list[dict[str, Any]]:
    rows = [
        _row(symbol, start),
        _row(symbol, start + timedelta(days=1), breakout=0.3),
        _row(symbol, start + timedelta(days=2)),
    ]
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


def test_v1_parameter_lattices_have_only_the_six_declared_dimensions() -> None:
    config = load_markup_retest_config()
    entries = entry_parameter_grid(config)

    assert len(entries) == 81
    assert len({item.parameter_id for item in entries}) == 81
    assert all(
        item.distribution_score_min == config.parameters.distribution_score_min
        and item.protective_stop_atr == config.parameters.protective_stop_atr
        for item in entries
    )
    for entry in entries:
        exits = exit_parameter_grid(config, entry)
        assert len(exits) == 9
        assert len({item.parameter_id for item in exits}) == 9
        assert all(
            item.setup_score_min == entry.setup_score_min
            and item.breakout_buffer_atr == entry.breakout_buffer_atr
            and item.max_retest_depth_atr == entry.max_retest_depth_atr
            and item.min_cost_migration_atr == entry.min_cost_migration_atr
            for item in exits
        )


def test_entry_lattice_reads_predictor_panel_once_and_emits_zero_counts() -> None:
    config = load_markup_retest_config()
    rows = _complete_signal_rows(
        "000001.SZ", date(2020, 6, 15), panel_snapshot_id="panel-1"
    )
    yielded = 0

    def records():
        nonlocal yielded
        for row in rows:
            yielded += 1
            yield row

    result = screen_entry_lattice(records(), config)

    assert yielded == len(rows)
    assert result.panel_passes == 1
    assert result.input_rows == len(rows)
    assert len(result.signal_counts) == 81
    assert len(result.evaluation_signal_counts) == 81
    assert set(result.annual_evaluation_signal_counts) == set(result.signal_counts)


def test_vector_lattice_matches_canonical_scalar_lifecycle_for_all_entries() -> None:
    config = load_markup_retest_config()
    rows = _complete_signal_rows(
        "000001.SZ", date(2020, 6, 15), panel_snapshot_id="panel-1"
    )
    # These values intentionally split the lattice along setup, breakout and
    # migration thresholds while satisfying every retest-depth threshold.
    for row in rows:
        row["setup_score"] = 0.8
    vector = screen_entry_lattice(rows, config, panel_snapshot_id="panel-1")
    vector_keys = {
        (str(row["parameter_id"]), str(row["signal_id"]))
        for row in vector.signals
    }

    scalar_keys: set[tuple[str, str]] = set()
    for parameters in entry_parameter_grid(config):
        generated = generate_signal_events(
            rows,
            config,
            parameters=parameters,
            panel_snapshot_id="panel-1",
        )
        scalar_keys.update(
            (parameters.parameter_id, str(row["signal_id"]))
            for row in generated.signals
        )

    assert vector_keys == scalar_keys
    assert len(vector_keys) == 24


def test_vector_lattice_matches_scalar_across_share_action() -> None:
    config = load_markup_retest_config()
    rows = _complete_signal_rows(
        "000001.SZ", date(2020, 6, 15), panel_snapshot_id="panel-action"
    )
    for row in rows:
        row["setup_score"] = 0.8
    retest = rows[-1]
    retest.update(
        {
            "share_multiplier": 2.0,
            "cash_per_share": 0.0,
            "corporate_action_ids": "action-20200617",
            "chip_histogram_prices": [4.75, 4.9, 5.1],
            "cost_p10": 4.75,
            "cost_p90": 5.1,
            "structure_support": 5.0,
            "close": 5.1,
            "low": 4.95,
            "average_cost": 4.9,
            "cost_p50": 4.9,
            "peak_track_band_lower": 4.75,
            "peak_track_band_upper": 5.1,
            "prior_average_cost": 4.75,
            "prior_cost_p50": 4.75,
            "atr": 0.5,
        }
    )

    vector = screen_entry_lattice(rows, config, panel_snapshot_id="panel-action")
    vector_keys = {
        (str(row["parameter_id"]), str(row["signal_id"]))
        for row in vector.signals
    }
    scalar_keys: set[tuple[str, str]] = set()
    for parameters in entry_parameter_grid(config):
        generated = generate_signal_events(
            rows,
            config,
            parameters=parameters,
            panel_snapshot_id="panel-action",
        )
        scalar_keys.update(
            (parameters.parameter_id, str(row["signal_id"]))
            for row in generated.signals
        )

    assert vector_keys == scalar_keys
    assert len(vector_keys) == 24


def test_entry_lattice_cannot_read_future_labels() -> None:
    config = load_markup_retest_config()
    rows = _complete_signal_rows("000001.SZ", date(2020, 6, 15))
    rows[0]["return_20d"] = 0.5

    with pytest.raises(FutureDataError, match="return_20d"):
        screen_entry_lattice(rows, config)


def test_parallel_entry_lattice_merge_matches_one_symbol_ordered_pass() -> None:
    config = load_markup_retest_config()
    first_rows = _complete_signal_rows("000001.SZ", date(2020, 6, 15))
    second_rows = _complete_signal_rows("600000.SH", date(2021, 6, 15))

    merged = _merge_entry_lattice_results(
        (
            screen_entry_lattice(first_rows, config),
            screen_entry_lattice(second_rows, config),
        ),
        collect_signals=True,
    )
    serial = screen_entry_lattice((*first_rows, *second_rows), config)

    assert merged.panel_passes == serial.panel_passes == 1
    assert merged.input_rows == serial.input_rows
    assert merged.evaluation_rows == serial.evaluation_rows
    assert merged.signal_counts == serial.signal_counts
    assert merged.evaluation_signal_counts == serial.evaluation_signal_counts
    assert (
        merged.annual_evaluation_signal_counts
        == serial.annual_evaluation_signal_counts
    )
    assert {
        (row["parameter_id"], row["signal_id"]) for row in merged.signals
    } == {
        (row["parameter_id"], row["signal_id"]) for row in serial.signals
    }
