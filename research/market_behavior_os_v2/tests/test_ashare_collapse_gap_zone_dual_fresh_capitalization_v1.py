# ruff: noqa: E501
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_dual_fresh_capitalization_v1 as capitalization,
)


@pytest.fixture(scope="module")
def result() -> dict[str, object]:
    return json.loads(capitalization.RESULT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ledger() -> pd.DataFrame:
    frame = pd.read_parquet(capitalization.TRADES)
    for column in ("entry_date", "entry_time", "exit_date", "exit_time"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def test_exact_dual_fresh_source_and_frozen_inputs() -> None:
    capitalization.validate_inputs()
    dual, trades, _daily = capitalization.load_dual_source()
    assert len(dual) == len(trades) == 207
    assert dual.groupby("board").size().to_dict() == {"CHINEXT": 76, "MAIN": 131}
    assert dual.L3_DUAL_FRESH.all()
    assert (dual.zone_age_sessions <= 90).all()
    assert (dual.cum_turnover_since_zone <= dual.turnover_train_q66_67).all()


def test_position_sizing_unused_cash_and_no_leverage(ledger: pd.DataFrame) -> None:
    executed = ledger.loc[ledger.status.eq("EXECUTED")]
    for k in capitalization.KS:
        part = executed.loc[executed.k.eq(k)]
        assert np.allclose(part.initial_weight, 1 / k, rtol=0, atol=1e-12)
        expected_qty = part.entry_outlay / (
            part.event_id.map(pd.read_parquet(capitalization.predecessor.TRADES).set_index("event_id").entry_raw_price)
            * (1 + capitalization.strategy.COST)
        )
        assert np.allclose(part.qty, expected_qty, rtol=0, atol=1e-12)
    for path in (capitalization.MAIN_NAV, capitalization.CHINEXT_NAV):
        nav = pd.read_parquet(path)
        assert nav.cash.min() >= -1e-12
        assert (nav.gross_exposure - nav.nav).max() <= 1e-12
        assert (nav.active_positions <= nav.k).all()


def test_capacity_skips_occur_only_at_full_k_and_order_is_frozen(ledger: pd.DataFrame) -> None:
    fixture = pd.DataFrame(
        [
            {"entry_time": pd.Timestamp("2020-01-02 10:00"), "primary_layer_width_pct": .1, "board_relative_return_percentile": .8, "peak_to_low_decline": .4, "persistence_sessions": 20, "symbol": "B"},
            {"entry_time": pd.Timestamp("2020-01-02 10:00"), "primary_layer_width_pct": .2, "board_relative_return_percentile": .7, "peak_to_low_decline": .3, "persistence_sessions": 10, "symbol": "A"},
        ]
    )
    assert capitalization.order_signals(fixture).symbol.tolist() == ["A", "B"]
    for (_board, k), part in ledger.groupby(["board", "k"], sort=True):
        active: dict[str, pd.Timestamp] = {}
        for row in part.sort_values(["entry_time", "event_id"], kind="mergesort").itertuples(index=False):
            active = {symbol: exit_time for symbol, exit_time in active.items() if pd.isna(exit_time) or exit_time > row.entry_time}
            if row.status == "SKIPPED_CAPACITY":
                assert len(active) >= k
            elif row.status == "EXECUTED":
                assert row.symbol not in active
                assert len(active) < k
                active[row.symbol] = row.exit_time
    assert int(ledger.loc[ledger.k.eq(5), "capacity_skip"].sum()) == 12
    assert int(ledger.loc[ledger.k.isin([10, 20]), "capacity_skip"].sum()) == 0


def test_k20_exactly_reproduces_predecessor() -> None:
    _dual, trades, daily = capitalization.load_dual_source()
    replays = {board: {20: capitalization.replay_k(trades, daily, board, 20)} for board in capitalization.BOARDS}
    assert capitalization.verify_k20_anchor(replays) == {
        "k20_nav_mismatch_count": 0,
        "k20_trade_identity_mismatch_count": 0,
        "k20_quantity_mismatch_count": 0,
    }


def test_t1_h40_u_and_corporate_actions_are_preserved() -> None:
    _dual, trades, _daily = capitalization.load_dual_source()
    assert trades.time_stop.eq(40).all()
    completed = trades.loc[trades.exit_time.notna()]
    assert (completed.exit_time > completed.entry_time).all()
    assert (completed.exit_date > completed.entry_date).all()
    assert completed.loc[completed.exit_reason.eq("TARGET"), "target_coord"].notna().all()
    risk = completed.loc[completed.exit_reason.eq("CORPORATE_ACTION_RISK")]
    assert (risk.exit_date < risk.risk_exit_effective_date).all()
    assert trades.action_block_time.isna().all()


def test_annual_nav_cagr_utilization_and_combination(result: dict[str, object]) -> None:
    board_nav = {
        "MAIN": pd.read_parquet(capitalization.MAIN_NAV),
        "CHINEXT": pd.read_parquet(capitalization.CHINEXT_NAV),
    }
    for board in capitalization.BOARDS:
        board_nav[board]["trade_date"] = pd.to_datetime(board_nav[board].trade_date)
    for k in capitalization.KS:
        main = board_nav["MAIN"].loc[board_nav["MAIN"].k.eq(k)].reset_index(drop=True)
        chinext = board_nav["CHINEXT"].loc[board_nav["CHINEXT"].k.eq(k)].reset_index(drop=True)
        combined = capitalization.combined_nav(main, chinext, k)
        assert np.allclose(combined.nav, .5 * main.nav + .5 * chinext.nav, rtol=0, atol=1e-12)
        expected_cagr = combined.nav.iloc[-1] ** (252 / len(combined)) - 1
        item = result["summary"]["COMBINED"][str(k)]
        assert item["cagr"] == pytest.approx(expected_cagr, abs=1e-12)
        assert item["average_gross_capital_utilization"] == pytest.approx((combined.gross_exposure / combined.nav).mean(), abs=1e-12)
        assert capitalization.annual_returns(combined) == pytest.approx(item["annual_returns"], abs=1e-12)


def test_concentration_and_sealed_boundaries(result: dict[str, object]) -> None:
    for k in capitalization.KS:
        item = result["summary"]["COMBINED"][str(k)]
        assert item["largest_single_position_weight"] == pytest.approx(1 / (2 * k))
        assert item["largest_one_day_nav_loss"] <= 0 <= item["largest_one_day_nav_gain"]
        assert 0 <= item["top1_pnl_day_contribution"] <= item["top5_pnl_day_contribution"] <= 1
        assert 0 <= item["top1_trade_pnl_contribution"] <= item["top5_trade_pnl_contribution"] <= 1
    assert result["verdict"] == "DUAL_FRESH_K10_PREFERRED"
    assert result["final_development_k_candidate"] == "CAP_K10"
    assert all(value == 0 for value in result["audit"].values())
    assert result["validation_opened"] is False
    assert result["repository_2024_plus_data_opened"] is False
