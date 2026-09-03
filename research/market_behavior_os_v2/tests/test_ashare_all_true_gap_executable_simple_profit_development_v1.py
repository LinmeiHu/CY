from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pypdf import PdfReader

from research.market_behavior_os_v2.scripts import (
    run_ashare_all_true_gap_executable_simple_profit_development_v1 as research,
)


def test_contract_uses_all_true_gaps_and_keeps_2021_plus_unread() -> None:
    contract = json.loads(Path(research.CONTRACT).read_text(encoding="utf-8"))
    assert contract["source"]["source_population_count"] == 88_785
    assert contract["source"]["v6_core_gate_used"] is False
    assert contract["source"]["v2_305_outcome_selected_rows_used"] is False
    assert contract["source"]["raw_tick_causal_mother_rebuilt_before_returns"] is True
    assert contract["chronology"]["reserved_2021_plus"] == "UNREAD"
    assert contract["governance"]["strategy_outcomes_2021_plus"] is False


def test_raw_tick_mapping_does_not_promote_adjusted_coordinate_rounding() -> None:
    assert research._price_ticks(np.array([4.479999999, 4.480000001])).tolist() == [448, 448]
    # A raw 4.45 high cannot touch a raw 4.48 boundary, even if adjusted
    # coordinates happen to round to the same cent.
    factor = np.array([0.25])
    boundary = 4.48 * factor[0]
    assert not research._raw_tick_reached(np.array([4.45]), boundary, factor)[0]
    assert research._raw_tick_reached(np.array([4.48]), boundary, factor)[0]


def test_stage_a_freeze_has_exact_history_and_no_outcome_access() -> None:
    freeze = json.loads(Path(research.FREEZE).read_text(encoding="utf-8"))
    funnel = freeze["raw_tick_funnel"]
    assert funnel == {
        "all_true_gaps": 88_785,
        "width_ge_1pct": 37_459,
        "daily_exact_history": 22_709,
        "raw_tick_pristine_first_return": 12_474,
        "daily_vap_eligible": 3_346,
        "exact_120x241_minute_history": 3_346,
        "low_inventory_before_exact_minute": 2_382,
        "corrected_mother": 2_361,
    }
    assert freeze["outcome_columns_in_source"] == []
    assert freeze["return_analysis_run"] == "NO"
    assert freeze["strategy_backtest_run"] == "NO"
    assert freeze["data_2021_or_later_used"] == "NO"
    assert freeze["repository_2024_plus_data_opened"] == "NO"


def test_walkforward_rule_and_execution_audits_are_frozen() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    selections = pd.DataFrame(result["walkforward_selections"])
    assert selections.outer_year.tolist() == [2017, 2018, 2019, 2020]
    assert selections.entry_form.eq("E1_CLOSE_L").all()
    assert selections.minimum_net_headroom.eq(0.015).all()
    assert selections.exit_policy.eq("X1_CLOSE_BELOW_L").all()
    assert selections.time_stop.eq(10).all()
    assert selections.deployment_ready.eq(False).all()
    assert selections.condition_count.max() <= 3
    audit = result["audit"]
    assert audit["stage_a_hash_reproduced"] is True
    assert audit["entry_uses_future_bar_count"] == 0
    assert audit["t1_violation_count"] == 0
    assert audit["impossible_exit_price_count"] == 0
    assert audit["post_2020_entry_count"] == 0
    assert audit["repository_2021_plus_data_opened"] == "NO"
    assert audit["repository_2024_plus_data_opened"] == "NO"


def test_result_is_marginal_not_a_profitable_strategy_claim() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    forced = result["procedures"]["FORCED_SELECTED"]["COMBINED"]
    fixed = result["procedures"]["FIXED_HUMAN_SIMPLE"]["COMBINED"]
    assert result["verdict"] == "SIMPLE_RULE_MARGINAL"
    assert result["is_profitable_simple_rule_created"] is False
    assert forced["trades"] == 330
    assert forced["mean_net"] > 0
    assert forced["return_excluding_best_five_days"] < 0
    assert fixed["trades"] == 114
    assert fixed["mean_net"] < 0
    assert fixed["cagr"] < 0


def test_complete_signal_book_is_uniform_and_hashed() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    index = pd.read_csv(research.CHART_INDEX)
    reader = PdfReader(str(research.PDF))
    assert len(index) == result["charts"]["signals"] == 355
    assert index.gap_id.is_unique
    assert len(reader.pages) == result["charts"]["pages"] == 356
    assert research.sha256(research.PDF) == result["charts"]["pdf_sha256"]
    signal_page_sizes = {
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in reader.pages[1:]
    }
    assert len(signal_page_sizes) == 1
