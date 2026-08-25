from __future__ import annotations

from typing import Any

import pytest

from cyq_game.strategy.economic_evaluation import (
    capacity_industry,
    combined_gate_metrics,
    paired_weekly_difference_evidence,
    replay_economic_metrics,
)


def _signal(
    signal_id: str,
    decision: str,
    entry: str | None,
    *,
    market: str = "RISK_ON",
    sector: str = "STRONG",
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "decision_at": decision,
        "entry_status": "FILLED" if entry else "FAILED",
        "entry_fill_at": entry,
        "is_evaluation_row": True,
        "market_state": market,
        "sector_state": sector,
    }


def _trade(
    signal_id: str,
    signal_at: str,
    exit_at: str,
    net_pnl: float,
    return_fraction: float,
    *,
    blocked: float = 0.0,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "signal_at": signal_at,
        "exit_at": exit_at,
        "entry_cash": 500_000.0,
        "net_pnl": net_pnl,
        "return_fraction": return_fraction,
        "blocked_tail_loss": blocked,
        "is_evaluation_row": True,
    }


def test_replay_metrics_use_exact_closures_and_raw_capacity_exposure() -> None:
    signals = (
        _signal("a", "2020-01-01T15:30:00+08:00", "2020-01-02T09:35:00+08:00"),
        _signal("b", "2020-01-02T15:30:00+08:00", "2020-01-03T09:35:00+08:00"),
        _signal("c", "2020-01-03T15:30:00+08:00", "2020-01-04T09:35:00+08:00"),
        _signal("d", "2020-01-04T15:30:00+08:00", None),
    )
    trades = (
        _trade(
            "a",
            "2020-01-01T15:30:00+08:00",
            "2020-01-05T09:35:00+08:00",
            50_000.0,
            0.10,
        ),
        _trade(
            "b",
            "2020-01-02T15:30:00+08:00",
            "2020-01-06T09:35:00+08:00",
            -25_000.0,
            -0.05,
            blocked=1_000.0,
        ),
    )

    metrics = replay_economic_metrics(
        signals,
        trades,
        industry_by_signal={"a": "I1", "b": "I1", "c": "I2"},
        entry_participation_by_signal={"a": 0.02, "b": 0.10, "c": 0.20},
        parameter_id="parameter",
    )

    assert metrics["entry_fill_rate"] == pytest.approx(0.75)
    assert metrics["closed_trade_rate"] == pytest.approx(2 / 3)
    assert metrics["profit_factor"] == pytest.approx(2.0)
    assert metrics["maximum_concurrent_positions"] == 3
    assert metrics["maximum_concurrent_same_industry_positions"] == 2
    assert metrics["open_positions_at_end"] == 1
    assert metrics["first_5m_participation_max"] == pytest.approx(0.20)
    assert metrics["blocked_tail_loss_ratio"] == pytest.approx(0.001)
    assert metrics["annual_signal_counts"] == {2020: 4}


def test_capacity_join_fails_closed_when_filled_signal_metadata_is_missing() -> None:
    signal = _signal(
        "a", "2020-01-01T15:30:00+08:00", "2020-01-02T09:35:00+08:00"
    )

    with pytest.raises(ValueError, match="incomplete causal capacity joins"):
        replay_economic_metrics(
            (signal,),
            (),
            industry_by_signal={},
            entry_participation_by_signal={},
            parameter_id="parameter",
        )


def test_paired_weekly_baseline_bootstrap_is_deterministic() -> None:
    pairs = tuple(
        {
            "candidate_signal_at": f"2020-01-{day:02d}T15:30:00+08:00",
            "candidate_return_fraction": 0.03,
            "baseline_return_fraction": 0.01,
        }
        for day in range(1, 15)
    )

    first = paired_weekly_difference_evidence(
        pairs, parameter_id="parameter", resamples=100
    )
    second = paired_weekly_difference_evidence(
        pairs, parameter_id="parameter", resamples=100
    )

    assert first == second
    assert first["baseline_pair_count"] == 14
    assert first["baseline_difference_trimmed_mean"] == pytest.approx(0.02)
    assert first["baseline_difference_lower_95"] == pytest.approx(0.02)


def test_combined_gate_sufficiency_uses_weaker_primary_or_baseline_evidence() -> None:
    combined = combined_gate_metrics(
        {
            "distinct_signal_weeks": 120,
            "effective_sample": 500.0,
            "bootstrap_half_width": 0.006,
        },
        {
            "baseline_distinct_signal_weeks": 110,
            "baseline_effective_sample": 380.0,
            "baseline_difference_half_width": 0.008,
        },
    )

    assert combined["distinct_signal_weeks"] == 110
    assert combined["effective_sample"] == pytest.approx(380.0)
    assert combined["bootstrap_half_width"] == pytest.approx(0.008)


def test_capacity_industry_uses_declared_board_fallback_conservatively() -> None:
    assert (
        capacity_industry(
            {
                "panel_industry": None,
                "observed_industry": None,
                "sector_fallback": "BOARD_LOO",
                "board": "CHINEXT",
            }
        )
        == "BOARD_FALLBACK:CHINEXT"
    )
    assert (
        capacity_industry(
            {
                "panel_industry": "Semiconductors",
                "observed_industry": None,
                "sector_fallback": "INDUSTRY_LOO",
                "board": "MAIN_SH",
            }
        )
        == "Semiconductors"
    )
    with pytest.raises(ValueError, match="neither causal industry"):
        capacity_industry(
            {
                "panel_industry": None,
                "observed_industry": None,
                "sector_fallback": "UNKNOWN",
                "board": "MAIN_SZ",
            }
        )
