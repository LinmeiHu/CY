from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from cyq_game.strategy.exact_replay import (
    _coalesce_panel_groups,
    evaluate_exact_entry_lattice_symbol_vectorized,
    evaluate_exact_parameter_lattice_symbol,
)
from cyq_game.strategy.execution import ExecutionWindow
from cyq_game.strategy.markup_retest import (
    freeze_lifecycle_anchor,
    load_markup_retest_config,
)
from cyq_game.strategy.research import entry_parameter_grid, exit_parameter_grid
from cyq_game.strategy.signals import observation_from_record

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
        "model_spread_cost_p50": 0.0,
        "model_spread_cost_p90": 0.0,
        "model_spread_main_peak": 0.0,
        "peak_count": 1,
        "recent_band_overlap": 0.9,
        "structure_support": 10.0,
        "close": 10.2,
        "low": 9.9,
        "volume": 100.0 if is_breakout else 50.0,
        "turnover_fraction": 0.1 if is_breakout else 0.05,
        "average_cost": 9.8,
        "cost_p50": 9.8,
        "main_peak": 9.8,
        "prior_average_cost": 9.5,
        "prior_cost_p50": 9.5,
        "prior_main_peak": 9.5,
        "atr": 1.0,
        "share_multiplier": 1.0,
        "cash_per_share": 0.0,
        "structure_broken": False,
        "corporate_action_blocking": False,
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


def _rows(symbol: str, start: date, count: int) -> list[dict[str, Any]]:
    rows = [_row(symbol, start + timedelta(days=index)) for index in range(count)]
    rows[1]["breakout_excess_atr"] = 0.3
    rows[1]["volume"] = 100.0
    rows[1]["turnover_fraction"] = 0.1
    config = load_markup_retest_config()
    anchor = freeze_lifecycle_anchor(
        observation_from_record(rows[0], config, "panel-exact"),
        strategy_version=config.strategy_version,
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


def _window(
    day: date,
    *,
    price: float = 10.0,
    up_limit: float = 11.0,
    down_limit: float = 9.0,
) -> ExecutionWindow:
    volume = 10_000.0
    return ExecutionWindow(
        symbol="000001.SZ",
        trade_date=day,
        window_index=0,
        available_at=datetime.combine(day, time(9, 35), CN_TZ),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=price * volume,
        trade_status=1,
        up_limit_price=up_limit,
        down_limit_price=down_limit,
        market_rule_valid=True,
        hard_valid=True,
        snapshot_id=f"window-{day}",
        daily_snapshot_id=f"daily-{day}",
    )


def test_shortlist_shares_one_predictor_scan() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 5)
    parameters = exit_parameter_grid(config, config.parameters)[:2]
    yielded = 0

    def records():
        nonlocal yielded
        for row in rows:
            yielded += 1
            yield row

    result = evaluate_exact_parameter_lattice_symbol(
        records(),
        (_window(date(2020, 6, 18)),),
        tuple(row["trade_date"] for row in rows),
        config,
        parameters,
        panel_snapshot_id="panel-exact",
    )

    assert yielded == len(rows)
    assert result.panel_passes == 1
    assert result.input_rows == len(rows)
    assert {row["parameter_id"] for row in result.signals} == {
        item.parameter_id for item in parameters
    }


def test_delayed_entry_cannot_exit_before_actual_fill() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 5)
    # The first post-signal close would trigger a stop if the strategy falsely
    # treated the still-pending order as a filled position.
    rows[3]["close"] = 7.0
    rows[3]["low"] = 7.0
    first_day_pinned = _window(
        date(2020, 6, 18), price=11.0, up_limit=11.0
    )
    second_day_legal = _window(date(2020, 6, 19))

    result = evaluate_exact_parameter_lattice_symbol(
        rows,
        (first_day_pinned, second_day_legal),
        tuple(row["trade_date"] for row in rows),
        config,
        (config.parameters,),
        panel_snapshot_id="panel-exact",
    )

    assert len(result.signals) == 1
    assert result.signals[0]["entry_fill_at"].startswith("2020-06-19")
    assert result.trades == ()
    assert result.open_exposures[0]["status"] == "POSITION_OPEN"


def test_exit_waits_through_lower_limit_before_closing_position() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 7)
    # Entry fills on day 3.  The day-3 close then creates a protective exit.
    rows[3]["close"] = 7.0
    rows[3]["low"] = 7.0
    entry_window = _window(date(2020, 6, 18))
    pinned_exit = _window(
        date(2020, 6, 19), price=9.0, down_limit=9.0
    )
    legal_exit = _window(date(2020, 6, 20), price=9.4, down_limit=8.0)

    result = evaluate_exact_parameter_lattice_symbol(
        rows,
        (entry_window, pinned_exit, legal_exit),
        tuple(row["trade_date"] for row in rows),
        config,
        (config.parameters,),
        panel_snapshot_id="panel-exact",
    )

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["entry_at"].startswith("2020-06-18")
    assert trade["exit_intent_at"].startswith("2020-06-18")
    assert trade["exit_at"].startswith("2020-06-20")
    assert result.open_exposures == ()


def test_unreconciled_share_action_does_not_multiply_position() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 7)
    # The source claims a 2-for-1 action, but the raw-price coordinate did not
    # reset: the observed preclose still equals the prior raw close.  Fail the
    # symbol closed without applying the unproven quantity multiplier.
    rows[4]["share_multiplier"] = 2.0
    rows[4]["preclose"] = rows[3]["close"]
    entry_window = _window(date(2020, 6, 18))
    exit_window = _window(date(2020, 6, 20))

    result = evaluate_exact_parameter_lattice_symbol(
        rows,
        (entry_window, exit_window),
        tuple(row["trade_date"] for row in rows),
        config,
        (config.parameters,),
        panel_snapshot_id="panel-exact",
    )

    assert len(result.signals) == 1
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["exit_reason"] == "CORPORATE_ACTION"
    assert trade["exit_quantity"] == trade["entry_quantity"]
    assert trade["dividends"] == 0.0
    assert trade["return_fraction"] < 0.1
    assert result.open_exposures == ()


def test_vectorized_entry_grid_matches_scalar_exact_execution() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 7)
    rows[3]["close"] = 7.0
    rows[3]["low"] = 7.0
    windows = (
        _window(date(2020, 6, 18)),
        _window(date(2020, 6, 19), price=9.0, down_limit=9.0),
        _window(date(2020, 6, 20), price=9.4, down_limit=8.0),
    )
    parameters = entry_parameter_grid(config)
    market_dates = tuple(row["trade_date"] for row in rows)

    scalar = evaluate_exact_parameter_lattice_symbol(
        rows,
        windows,
        market_dates,
        config,
        parameters,
        panel_snapshot_id="panel-exact",
    )
    vectorized = evaluate_exact_entry_lattice_symbol_vectorized(
        rows,
        windows,
        market_dates,
        config,
        parameters,
        panel_snapshot_id="panel-exact",
    )

    assert vectorized == scalar


def test_vectorized_entry_grid_matches_action_coordinate_fail_closed() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 7)
    rows[4]["share_multiplier"] = 2.0
    rows[4]["preclose"] = rows[3]["close"]
    windows = (
        _window(date(2020, 6, 18)),
        _window(date(2020, 6, 20)),
    )
    parameters = entry_parameter_grid(config)
    market_dates = tuple(row["trade_date"] for row in rows)

    scalar = evaluate_exact_parameter_lattice_symbol(
        rows,
        windows,
        market_dates,
        config,
        parameters,
        panel_snapshot_id="panel-exact",
    )
    vectorized = evaluate_exact_entry_lattice_symbol_vectorized(
        rows,
        windows,
        market_dates,
        config,
        parameters,
        panel_snapshot_id="panel-exact",
    )

    assert vectorized == scalar


def test_vectorized_entry_grid_matches_delayed_and_failed_entries() -> None:
    config = load_markup_retest_config()
    rows = _rows("000001.SZ", date(2020, 6, 15), 8)
    parameters = entry_parameter_grid(config)
    market_dates = tuple(row["trade_date"] for row in rows)

    for windows in (
        (
            _window(date(2020, 6, 18), price=11.0, up_limit=11.0),
            _window(date(2020, 6, 19)),
        ),
        (
            _window(date(2020, 6, 18), price=11.0, up_limit=11.0),
            _window(date(2020, 6, 19), price=11.0, up_limit=11.0),
            _window(date(2020, 6, 20), price=11.0, up_limit=11.0),
        ),
    ):
        scalar = evaluate_exact_parameter_lattice_symbol(
            rows,
            windows,
            market_dates,
            config,
            parameters,
            panel_snapshot_id="panel-exact",
        )
        vectorized = evaluate_exact_entry_lattice_symbol_vectorized(
            rows,
            windows,
            market_dates,
            config,
            parameters,
            panel_snapshot_id="panel-exact",
        )

        assert vectorized == scalar


def test_execution_scan_buckets_are_coalesced_once_per_worker(tmp_path) -> None:
    groups = []
    for bucket in range(32):
        path = tmp_path / f"bucket-{bucket}.parquet"
        path.write_bytes(b"x" * (bucket + 1))
        groups.append((bucket, (path,)))

    coalesced = _coalesce_panel_groups(tuple(groups), 4)

    assert len(coalesced) == 4
    assert sorted(bucket for buckets, _ in coalesced for bucket in buckets) == list(
        range(32)
    )
    assert sorted(path for _, paths in coalesced for path in paths) == sorted(
        path for _, paths in groups for path in paths
    )
