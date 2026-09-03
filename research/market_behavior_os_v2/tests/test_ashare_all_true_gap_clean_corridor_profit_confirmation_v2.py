from __future__ import annotations

import json

import numpy as np
import pandas as pd
from pypdf import PdfReader

from research.market_behavior_os_v2.scripts import (
    run_ashare_all_true_gap_clean_corridor_profit_confirmation_v2 as research,
)


def test_contract_freezes_complete_2021_first_return_cohort() -> None:
    contract = json.loads(research.CONTRACT.read_text(encoding="utf-8"))
    assert contract["source"]["v6_core_gate_used"] is False
    assert contract["source"]["v2_selected_305_used"] is False
    assert contract["source"]["confirmation_gap_cohort"] == (
        "all governed 2014-2021 gaps whose first exact raw-fen return occurs in 2021"
    )
    assert contract["chronology"]["one_shot_confirmation"] == [
        "2021-01-01",
        "2021-12-31",
    ]
    assert contract["chronology"]["2022_and_later_used"] is False
    assert contract["fixed_simple_rule"]["condition_1"].endswith(
        "<=2.5 times mean bin mass in z=[-2,3)"
    )
    assert research.MIN_PEAK_TO_GAP_SESSIONS == 60
    assert research.MAX_PRE_GAP_20D_RANGE == 0.20
    assert research.MINIMUM_NET_HEADROOM == 0.015
    assert research.PRIMARY_K == 2


def test_raw_fen_touch_mapping_is_not_adjusted_coordinate_rounding() -> None:
    prices = np.array([4.479999999, 4.480000001])
    assert research._price_ticks(prices).tolist() == [448, 448]
    factor = np.array([0.25])
    boundary = 4.48 * factor[0]
    assert not research._raw_tick_reached(np.array([4.45]), boundary, factor)[0]
    assert research._raw_tick_reached(np.array([4.48]), boundary, factor)[0]


def test_stage_a_is_reproducible_and_outcome_blind() -> None:
    freeze = json.loads(research.FREEZE.read_text(encoding="utf-8"))
    assert freeze["funnel"] == {
        "all_true_gaps_2014_2021": 98_750,
        "new_true_gaps_2021": 9_965,
        "width_ge_1pct": 40_872,
        "daily_exact_history": 25_289,
        "pristine_raw_tick_return": 14_197,
        "daily_vap_eligible_with_h10_room": 550,
        "exact_120x241_history": 550,
        "broad_low_inventory": 348,
        "fixed_clean_corridor_nonacute": 62,
        "executable_entries": 32,
    }
    assert freeze["entry_status"] == {
        "EXECUTABLE_ENTRY": 32,
        "NO_TRIGGER_BEFORE_FAST_REPAIR": 30,
    }
    assert freeze["outcome_columns_in_fixed_mother"] == []
    assert freeze["design_outcomes_opened_in_stage_a"] == "NO"
    assert freeze["confirmation_outcomes_opened_in_stage_a"] == "NO"
    assert freeze["data_2022_or_later_opened"] == "NO"


def test_confirmation_includes_cross_year_gaps_and_remains_causal() -> None:
    fixed = pd.read_parquet(research.FIXED_MOTHER_2021)
    entries = pd.read_parquet(research.ENTRIES_2021)
    fixed["gap_date"] = pd.to_datetime(fixed.gap_date)
    fixed["first_return_date"] = pd.to_datetime(fixed.first_return_date)
    assert len(fixed) == 62
    assert fixed.gap_id.is_unique
    assert fixed.first_return_date.dt.year.eq(2021).all()
    assert fixed.gap_date.dt.year.lt(2021).sum() == 8
    assert fixed.pre_gap_corridor_max_bin_density_relative_local.le(2.5).all()
    assert fixed.pre_peak_to_gap_sessions.ge(60).all()
    assert fixed.pre_gap_range_20d.le(0.20).all()
    assert entries.entry_key.is_unique
    assert not entries.entry_uses_future_bar.any()
    assert not entries.entry_is_2022_or_later.any()


def test_one_shot_result_is_positive_but_board_divergent() -> None:
    result = json.loads(research.RESULT.read_text(encoding="utf-8"))
    primary = result["portfolio"]["ONE_SHOT_2021_CONFIRMATION"]["K2"]
    combined = primary["COMBINED"]
    assert result["verdict"] == "ONE_YEAR_CLEAN_CORRIDOR_EDGE_CONFIRMED"
    assert combined["signals"] == 28
    assert combined["trades"] == 24
    assert np.isclose(combined["mean_net"], 0.010425709671326291)
    assert np.isclose(combined["median_net"], 0.017401091431406668)
    assert np.isclose(combined["win"], 14 / 24)
    assert np.isclose(combined["total_return"], 0.06907324003176818)
    assert np.isclose(combined["max_drawdown"], -0.05659185389144039)
    assert np.isclose(combined["sharpe"], 1.398959161742391)
    assert combined["return_excluding_best_day"] > 0
    assert combined["return_excluding_best_five_days"] < 0
    assert primary["MAIN"]["total_return"] > 0
    assert primary["CHINEXT"]["total_return"] < 0
    assert result["audit"]["entry_uses_future_bar_count"] == 0
    assert result["audit"]["t1_violation_count"] == 0
    assert result["audit"]["impossible_exit_price_count"] == 0
    assert result["audit"]["data_2022_or_later_opened"] == "NO"


def test_outcome_and_portfolio_reconciliation() -> None:
    outcomes = pd.read_parquet(research.OUTCOMES_2021)
    ledger = pd.read_parquet(research.PORTFOLIO_LEDGER)
    accepted = pd.read_parquet(research.PORTFOLIO_ACCEPTED)
    primary_ledger = ledger.loc[
        ledger["sample"].eq("ONE_SHOT_2021_CONFIRMATION") & ledger.k.eq(2)
    ]
    primary_accepted = accepted.loc[
        accepted["sample"].eq("ONE_SHOT_2021_CONFIRMATION") & accepted.k.eq(2)
    ]
    assert len(outcomes) == 32
    assert outcomes.outcome_valid.sum() == 28
    assert not outcomes.t1_violation.any()
    assert not outcomes.impossible_exit_price.any()
    assert primary_ledger.status.value_counts().to_dict() == {
        "EXECUTED": 24,
        "SKIPPED_INSUFFICIENT_CASH": 4,
    }
    assert len(primary_accepted) == 24


def test_complete_chart_book_is_hashed_and_uniform() -> None:
    result = json.loads(research.RESULT.read_text(encoding="utf-8"))
    index = pd.read_csv(research.CHART_INDEX)
    reader = PdfReader(str(research.PDF))
    assert len(index) == result["charts"]["signals"] == 182
    assert index["sample"].value_counts().to_dict() == {
        "DEVELOPMENT_DESIGN_ALREADY_CONSUMED": 154,
        "ONE_SHOT_2021_CONFIRMATION": 28,
    }
    assert len(reader.pages) == result["charts"]["pages"] == 183
    assert research.sha256(research.PDF) == result["charts"]["pdf_sha256"]
    signal_page_sizes = {
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in reader.pages[1:]
    }
    assert len(signal_page_sizes) == 1
