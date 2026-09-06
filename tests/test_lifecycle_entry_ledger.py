from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cyq_game.domain import FutureDataError
from cyq_game.strategy.exact_replay import evaluate_exact_parameter_lattice_symbol
from cyq_game.strategy.execution import ExecutionReason, ExecutionWindow
from cyq_game.strategy.lifecycle_ledger import (
    LifecycleLedgerProvenance,
    replay_lifecycle_entry_ledger,
    write_lifecycle_ledger_artifact,
)
from cyq_game.strategy.markup_retest import (
    StrategyParameters,
    freeze_lifecycle_anchor,
    load_markup_retest_config,
)
from cyq_game.strategy.signals import observation_from_record

CN_TZ = timezone(timedelta(hours=8))


@pytest.fixture(scope="module")
def config():
    return load_markup_retest_config()


@pytest.fixture(scope="module")
def parameters() -> StrategyParameters:
    selected = StrategyParameters(
        setup_score_min=1.0,
        breakout_buffer_atr=0.25,
        max_retest_depth_atr=0.5,
        min_cost_migration_atr=0.5,
        distribution_score_min=0.8,
        protective_stop_atr=1.5,
    )
    assert selected.parameter_id == "9baed76ec299161c"
    return selected


@pytest.fixture(scope="module")
def provenance() -> LifecycleLedgerProvenance:
    symbol = "000001.SZ"
    return LifecycleLedgerProvenance(
        v3_root_manifest_sha256="1" * 64,
        v3_root_id="v12-root-test",
        code_commit="2" * 40,
        semantic_fingerprint="3" * 64,
        chip_artifact_fingerprint="4" * 64,
        replay_parameter_digest="5" * 64,
        panel_snapshot_id="panel-ledger-test",
        semantic_epoch="semantic-test-v1",
        code_file_sha256={
            "lifecycle_ledger.py": "8" * 64,
            "markup_retest.py": "9" * 64,
            "execution.py": "a" * 64,
            "exact_replay.py": "b" * 64,
        },
        symbol_manifest_sha256={symbol: "6" * 64},
        input_manifest_sha256={symbol: "7" * 64},
    )


def _row(day: date, *, breakout: float = 0.0) -> dict[str, Any]:
    decision_at = datetime.combine(day, time(15, 30), CN_TZ)
    is_breakout = breakout > 0
    return {
        "symbol": "000001.SZ",
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
        "setup_score": 1.0,
        "breakout_excess_atr": breakout,
        "support_regained": True,
        "chip_histogram_prices": [9.5, 9.8, 10.2],
        "chip_histogram_masses": [0.2, 0.6, 0.2],
        "cost_p10": 9.5,
        "cost_p90": 10.2,
        "known_cost_fraction_min": 1.0,
        "model_spread_cost_p50": 0.0,
        "model_spread_cost_p90": 0.0,
        "model_spread_dominant_peak_today": 0.0,
        "peak_track_id": "peak-track-A",
        "peak_track_band_lower": 9.5,
        "peak_track_band_upper": 10.2,
        "peak_track_ambiguous": False,
        "peak_definition_version": "canonical-chip-peak-v2",
        "peak_track_version": "temporal-chip-peak-v3",
        "peak_track_episode": 7,
        "peak_track_mass": 0.8,
        "peak_track_prominence": 0.6,
        "peak_track_split": False,
        "peak_track_merge": False,
        "peak_track_lost": False,
        "state_version": "chip-state-v3",
        "feature_config_sha256": "feature-config-test",
        "feature_code_sha256": "feature-code-test",
        "peak_count": 1,
        "recent_band_overlap": 0.9,
        "structure_support": 10.0,
        "close": 10.2,
        "preclose": 10.2,
        "close_vs_vwap": 0.01,
        "low": 9.9,
        "volume": 100.0 if is_breakout else 50.0,
        "turnover_fraction": 0.10 if is_breakout else 0.05,
        "average_cost": 10.0,
        "cost_p50": 10.0,
        "prior_average_cost": 9.5,
        "prior_cost_p50": 9.5,
        "atr": 1.0,
        "share_multiplier": 1.0,
        "cash_per_share": 0.0,
        "corporate_action_ids": "",
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
        "dist_base_loss": None,
        "exact_lineage_state": "UNKNOWN",
        "dist_cost_band_expands": False,
        "dist_peak_splits": False,
        "dist_high_turnover_weak_impact": False,
        "dist_relative_reversal": False,
        "is_evaluation_row": True,
    }


def _rows(config, start: date, count: int) -> list[dict[str, Any]]:
    rows = [_row(start + timedelta(days=index)) for index in range(count)]
    rows[1]["breakout_excess_atr"] = 0.3
    rows[1]["volume"] = 100.0
    rows[1]["turnover_fraction"] = 0.10
    root = freeze_lifecycle_anchor(
        observation_from_record(rows[0], config, "panel-ledger-test"),
        strategy_version=config.strategy_version,
    )
    for row in rows[1:]:
        row["anchor_retention_estimates"] = [
            {
                "anchor_id": root.anchor_id,
                "symbol": root.symbol,
                "anchor_date": root.created_at.isoformat(),
                "current_date": str(row["trade_date"]),
                "model_retentions": {
                    "UNIFORM": 0.82,
                    "DISPOSITION": 0.80,
                    "ACTIVE_STICKY": 0.78,
                },
                "ensemble_version": "test-v1",
            }
        ]
    return rows


def _window(
    day: date,
    *,
    index: int = 0,
    price: float = 10.0,
    up_limit: float = 11.0,
    down_limit: float = 9.0,
    trade_status: int = 1,
) -> ExecutionWindow:
    volume = 10_000.0
    return ExecutionWindow(
        symbol="000001.SZ",
        trade_date=day,
        window_index=index,
        available_at=datetime.combine(
            day, time(9, 35 + 5 * index), CN_TZ
        ),
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        amount=price * volume,
        trade_status=trade_status,
        up_limit_price=up_limit,
        down_limit_price=down_limit,
        market_rule_valid=True,
        hard_valid=True,
        snapshot_id=f"window-{day}-{index}",
        daily_snapshot_id=f"daily-{day}",
    )


def _replay(rows, windows, config, parameters, provenance):
    return replay_lifecycle_entry_ledger(
        rows,
        windows,
        tuple(row["trade_date"] for row in rows),
        config,
        parameters,
        provenance,
    )


def test_exact_lifecycle_entry_exit_and_frozen_quantities(
    config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 5)
    rows[3]["close"] = 7.0
    rows[3]["low"] = 7.0
    windows = (
        _window(rows[3]["trade_date"]),
        _window(rows[4]["trade_date"], price=9.4),
    )
    replay = _replay(
        rows,
        windows,
        config,
        parameters,
        provenance,
    )
    production = evaluate_exact_parameter_lattice_symbol(
        rows,
        windows,
        tuple(row["trade_date"] for row in rows),
        config,
        (parameters,),
        panel_snapshot_id=provenance.panel_snapshot_id,
    )

    setup, breakout, retest, entered, exited = replay.decisions
    assert setup["events"][:2] == ["SETUP_OBSERVED", "ROOT_ANCHOR_BOUND"]
    assert setup["quantities"]["accumulation_score"] == 1.0
    assert all(setup["quantities"]["accumulation_evidence"].values())
    assert breakout["events"] == ["SETUP_OBSERVED", "BREAKOUT_OBSERVED", "GATE_PASS"]
    assert breakout["quantities"] | {
        "frozen_support": 10.0,
        "frozen_atr": 1.0,
        "breakout_volume": 100.0,
        "breakout_turnover": 0.10,
        "pre_breakout_average_cost": 9.5,
        "pre_breakout_cost_p50": 9.5,
    } == breakout["quantities"]
    assert retest["qualified_signal"]
    assert retest["entry_intent"]
    assert not retest["formal_order_authorized"]
    assert retest["quantities"]["retest_depth_atr"] == pytest.approx(0.1)
    assert retest["quantities"]["cost_migration_atr"] == pytest.approx(0.5)
    assert retest["quantities"]["retest_volume_ratio"] == pytest.approx(0.5)
    assert retest["quantities"]["retest_turnover_ratio"] == pytest.approx(0.5)
    retention = retest["quantities"]["exact_root_retention"]
    assert retention["lower"] == 0.78
    assert retention["upper"] == 0.82
    assert retest["first_failed_gate"] is None
    assert entered["actual_legal_entry"]
    assert entered["exit_reason"] == "PROTECTIVE_STOP"
    assert "EXIT_INTENT" in entered["events"]
    assert exited["actual_legal_exit"]
    assert exited["lifecycle_terminated"]
    assert exited["lifecycle_termination_reason"] == "PROTECTIVE_STOP"

    actual_entry = [
        row for row in replay.execution_attempts if row["event"] == "ACTUAL_ENTRY"
    ]
    actual_exit = [
        row for row in replay.execution_attempts if row["event"] == "ACTUAL_EXIT"
    ]
    assert len(actual_entry) == len(actual_exit) == 1
    assert actual_entry[0]["attempted_at"].startswith("2020-06-18T09:35")
    assert actual_exit[0]["attempted_at"].startswith("2020-06-19T09:35")
    assert actual_entry[0]["decision_at"].startswith("2020-06-17T15:30")
    assert actual_exit[0]["decision_at"].startswith("2020-06-18T15:30")
    assert production.signals[0]["signal_id"] == retest["signal_id"]
    assert production.signals[0]["entry_fill_at"] == actual_entry[0]["fill_at"]
    assert production.trades[0]["exit_reason"] == entered["exit_reason"]
    assert production.trades[0]["exit_at"] == actual_exit[0]["fill_at"]


def test_rejected_retest_materializes_first_and_all_failed_gates(
    config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 3)
    rows[2]["model_spread_cost_p50"] = 3.01
    rows[2]["model_spread_cost_p90"] = 3.01
    rows[2]["model_spread_dominant_peak_today"] = 3.01

    replay = _replay(rows, (), config, parameters, provenance)
    retest = replay.decisions[-1]

    assert "RETEST_OBSERVED" in retest["events"]
    assert "REJECTION" in retest["events"]
    assert not retest["qualified_signal"]
    assert retest["first_failed_gate"] == "seller_model_disagreement_atr"
    assert retest["all_failed_gates"] == ["seller_model_disagreement_atr"]
    disagreement = next(
        gate
        for gate in retest["gates"]
        if gate["name"] == "seller_model_disagreement_atr"
    )
    assert disagreement == {
        "name": "seller_model_disagreement_atr",
        "passed": False,
        "value": 3.01,
        "operator": "<=",
        "threshold": 3.0,
    }


def test_qualified_but_not_executed_remains_distinct(
    config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 6)
    replay = _replay(rows, (), config, parameters, provenance)
    qualified = replay.decisions[2]

    assert qualified["qualified_signal"]
    assert qualified["entry_intent"]
    assert qualified["entry_execution_status"] == "FAILED"
    assert not qualified["actual_legal_entry"]
    assert not any(row["event"] == "ACTUAL_ENTRY" for row in replay.execution_attempts)
    assert [
        row["first_failed_gate"] for row in replay.execution_attempts
    ] == ["MISSING_EXECUTION_WINDOW"] * 3
    assert replay.decisions[5]["lifecycle_termination_reason"] == (
        "ENTRY_EXECUTION_FAILED"
    )


def test_entry_suspension_and_limit_then_exit_down_limit_are_explicit(
    config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 7)
    rows[4]["close"] = 7.0
    rows[4]["low"] = 7.0
    entry_day = rows[3]["trade_date"]
    fill_day = rows[4]["trade_date"]
    pinned_exit_day = rows[5]["trade_date"]
    legal_exit_day = rows[6]["trade_date"]
    replay = _replay(
        rows,
        (
            _window(entry_day, price=11.0, up_limit=11.0),
            _window(entry_day, index=1, trade_status=0),
            _window(fill_day),
            _window(pinned_exit_day, price=9.0, down_limit=9.0),
            _window(legal_exit_day, price=9.4, down_limit=8.0),
        ),
        config,
        parameters,
        provenance,
    )
    reasons = [
        reason
        for row in replay.execution_attempts
        for reason in row["all_failed_gates"]
    ]

    assert ExecutionReason.BUY_LIQUIDITY_BLOCKED_AT_UP_LIMIT.value in reasons
    assert ExecutionReason.SUSPENDED_OR_NOT_TRADABLE.value in reasons
    assert ExecutionReason.SELL_LIQUIDITY_BLOCKED_AT_DOWN_LIMIT.value in reasons
    assert any(row["event"] == "ACTUAL_ENTRY" for row in replay.execution_attempts)
    assert any(row["event"] == "ACTUAL_EXIT" for row in replay.execution_attempts)


def test_current_rolling_base_never_mutates_historical_root_anchor(
    config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 4)
    rows[3].update(
        {
            "peak_track_id": "peak-track-B",
            "peak_track_band_lower": 10.5,
            "peak_track_band_upper": 11.0,
            "peak_track_episode": 8,
        }
    )
    replay = _replay(
        rows,
        (_window(rows[3]["trade_date"]),),
        config,
        parameters,
        provenance,
    )
    changed = replay.decisions[3]

    assert changed["rolling_base_visible_at_decision"]["peak_track_id"] == (
        "peak-track-B"
    )
    assert changed["immutable_root_anchor"]["peak_track_id"] == "peak-track-A"
    assert changed["immutable_root_anchor"]["anchor_id"] == (
        replay.decisions[0]["immutable_root_anchor"]["anchor_id"]
    )
    assert changed["exit_reason"] == "STRUCTURE_BROKEN"


def test_adapter_preserves_absent_non_actionable_operands_as_null(
    config, parameters, provenance
) -> None:
    row = _row(date(2020, 1, 2))
    row.update(
        {
            "history_count": 0,
            "structure_support": None,
            "prior_average_cost": None,
            "prior_cost_p50": None,
        }
    )

    observation = observation_from_record(row, config, provenance.panel_snapshot_id)
    replay = _replay((row,), (), config, parameters, provenance)

    assert observation.structure_support is None
    assert observation.prior_average_cost is None
    assert observation.prior_cost_p50 is None
    assert replay.decisions[0]["events"][0] == "NO_SETUP"
    assert replay.decisions[0]["lifecycle_state_after"] == "NEUTRAL"


def test_pit_parameter_binding_and_deterministic_artifact_bytes(
    tmp_path: Path, config, parameters, provenance
) -> None:
    rows = _rows(config, date(2020, 6, 15), 4)
    window = _window(rows[3]["trade_date"])
    first = _replay(rows, (window,), config, parameters, provenance)
    second = _replay(rows, (window,), config, parameters, provenance)

    assert first == second
    assert first.canonical_digest == second.canonical_digest
    assert {row["parameter_id"] for row in first.decisions} == {
        "9baed76ec299161c"
    }
    left = write_lifecycle_ledger_artifact(tmp_path / "left", first)
    right = write_lifecycle_ledger_artifact(tmp_path / "right", second)
    write_lifecycle_ledger_artifact(tmp_path / "left", first)
    assert left.canonical_digest == right.canonical_digest
    assert {
        path.name: path.read_bytes() for path in left.path.iterdir()
    } == {path.name: path.read_bytes() for path in right.path.iterdir()}

    future = dict(rows[0])
    future["available_at"] = future["decision_at"] + timedelta(seconds=1)
    with pytest.raises(FutureDataError):
        _replay((future,), (), config, parameters, provenance)
