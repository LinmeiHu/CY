# ruff: noqa: E501
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_entry_admission_development_v1 as admission,
)


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return pd.read_parquet(admission.ADMISSION)


@pytest.fixture(scope="module")
def result() -> dict[str, object]:
    return json.loads(admission.RESULT.read_text(encoding="utf-8"))


def test_frozen_identity_and_sealed_periods(result: dict[str, object]) -> None:
    admission.validate_inputs()
    assert admission.v1.sha256_file(admission.SPEC) == admission.EXPECTED_SPEC_SHA256
    assert result["start_head"] == admission.START_HEAD
    assert result["validation_opened"] is False
    assert result["repository_2024_plus_data_opened"] is False
    assert all(value == 0 for value in result["audit"].values())


def test_four_lanes_and_train_only_cutoffs_are_exact(
    panel: pd.DataFrame, result: dict[str, object]
) -> None:
    assert len(panel) == 496 and panel.event_id.is_unique
    assert set(panel.entry_year) == set(admission.TEST_YEARS)
    assert panel.L0_BASELINE.all()
    assert panel.L1_AGE_FRESH.equals(panel.zone_age_sessions.le(90))
    assert panel.L2_TURNOVER_FRESH.equals(
        panel.cum_turnover_since_zone.le(panel.turnover_train_q66_67)
    )
    assert panel.L3_DUAL_FRESH.equals(panel.L1_AGE_FRESH & panel.L2_TURNOVER_FRESH)

    source = pd.read_parquet(admission.resolution.SOURCE)
    source = source.loc[~source.risk_blocked_entry, ["event_id", "board", "entry_date"]].copy()
    source["entry_year"] = pd.to_datetime(source.entry_date).dt.year
    turnover = pd.read_parquet(admission.FEATURE_DAILY).groupby("event_id").turnover_fraction.sum()
    source["turnover"] = source.event_id.map(turnover)
    assert source.turnover.notna().all()
    for train_start, train_end, test_year in admission.FOLDS:
        for board in admission.BOARDS:
            train = source.loc[
                source.board.eq(board) & source.entry_year.between(train_start, train_end),
                "turnover",
            ]
            expected = float(train.quantile(2 / 3, interpolation="linear"))
            frozen = result["source_reconciliation"]["cutoffs"][str(test_year)][board]
            assert frozen["test_rows_used"] == 0
            assert frozen["train_n"] == len(train)
            assert frozen["cutoff"] == pytest.approx(expected, abs=1e-12)


def test_h40_reproduces_all_prior_anatomy_events() -> None:
    trades = pd.read_parquet(admission.TRADES).set_index("event_id")
    anchor = pd.read_parquet(
        admission.anatomy.EVENTS,
        columns=["event_id", "full_or_h40_valid", "full_or_h40_net", "full_or_h40_exit_kind"],
    ).set_index("event_id")
    reconstructed = trades.loc[anchor.index]
    kind = reconstructed.exit_reason.map(
        {
            "TARGET": "TARGET",
            "TIME_STOP": "HORIZON_CLOSE",
            "TIME_STOP_DELAYED": "HORIZON_DELAYED",
            "CORPORATE_ACTION_RISK": "CORPORATE_ACTION_RISK",
        }
    )
    assert kind.notna().equals(anchor.full_or_h40_valid.astype(bool))
    assert kind.fillna("<NONE>").equals(anchor.full_or_h40_exit_kind.fillna("<NONE>"))
    for event_id, row in reconstructed.loc[kind.notna()].iterrows():
        cash = sum(float(item["cash_per_share"]) for item in json.loads(row.cash_events_json))
        net = (
            (float(row.exit_raw_price) * (1 - admission.strategy.COST) + cash)
            / (float(row.entry_raw_price) * (1 + admission.strategy.COST))
            - 1
        )
        assert net == pytest.approx(float(anchor.at[event_id, "full_or_h40_net"]), abs=1e-12)


def test_portfolio_capacity_cash_and_combined_nav_are_exact() -> None:
    nav = pd.read_parquet(admission.NAV)
    sleeves = nav.loc[nav.board.isin(admission.BOARDS)]
    assert sleeves.active_positions.max() <= 20
    assert sleeves.cash.min() >= -1e-12
    assert sleeves.gross_exposure.max() <= 1 + 1e-12
    for lane in admission.LANES:
        main = nav.loc[nav.board.eq("MAIN") & nav.lane.eq(lane)].set_index("trade_date").nav
        chinext = nav.loc[nav.board.eq("CHINEXT") & nav.lane.eq(lane)].set_index("trade_date").nav
        combined = nav.loc[nav.board.eq("COMBINED") & nav.lane.eq(lane)].set_index("trade_date").nav
        assert np.allclose(combined, 0.5 * main + 0.5 * chinext, rtol=0, atol=1e-12)


def test_year_tables_and_frozen_verdict_are_complete(result: dict[str, object]) -> None:
    required = {
        "signals", "executed_trades", "completed_trades", "signal_retention",
        "mean_net_trade_return", "median_net_trade_return", "positive_trade_rate",
        "full_u_target_hit_rate", "mean_holding_sessions", "median_holding_sessions",
        "portfolio_return",
    }
    for board in (*admission.BOARDS, "COMBINED"):
        for lane in admission.LANES:
            assert set(result["yearly"][board][lane]) == {str(year) for year in admission.TEST_YEARS}
            for item in result["yearly"][board][lane].values():
                assert required.issubset(item)
    assert result["verdict"] == "FRESHNESS_EDGE_BOARD_SPECIFIC"
    assert result["verdict_evidence"]["qualifying"] == ["L2_TURNOVER_FRESH", "L3_DUAL_FRESH"]
