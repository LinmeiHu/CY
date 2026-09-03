from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_low_inventory_fill_pattern_discovery_v1 as research,
)


def test_contract_is_descriptive_pre_2021_and_not_a_strategy() -> None:
    contract = research.contract_value()
    assert contract["scientific_status"] == (
        "PRE_2021_IN_SAMPLE_DESCRIPTIVE_PATTERN_DISCOVERY_NOT_PREDICTION_NOT_STRATEGY"
    )
    assert contract["chronology"]["discovery_end"] == "2020-12-31"
    assert contract["chronology"]["2021_and_later_used"] is False
    mother = contract["stage_a_outcome_blind_mother_population"]
    assert mother["inside_gap_density"]["maximum"] == 1.0
    assert mother["corridor_density"]["maximum"] == 1.0
    assert contract["stage_b_structural_outcome"]["return_or_pnl_opened"] is False
    assert contract["governance"]["prediction_analysis_run"] is False
    assert contract["governance"]["strategy_backtest_run"] is False


def test_stage_a_population_is_broad_low_inventory_and_complete() -> None:
    frame = pd.read_parquet(research.STAGE_A_LEDGER)
    assert len(frame) >= 100
    assert frame.candidate_id.is_unique
    assert pd.to_datetime(frame.causal_first_return).max() < pd.Timestamp("2021-01-01")
    assert frame.valid_pre_sessions.eq(120).all()
    assert frame.pre_gap_inside_density_relative_local.le(1.0).all()
    assert frame.pre_gap_corridor_density_relative_local.le(1.0).all()
    assert frame.pre_gap_inside_touch_sessions.le(12).all()
    assert frame.pre_gap_corridor_touch_sessions.le(20).all()
    assert frame.complete_h40_before_2021.all()


def test_descriptive_rule_has_at_most_three_conditions_and_no_return_fields() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    frame = pd.read_parquet(research.DISCOVERY_LEDGER)
    assert frame.u_fill_offset.dropna().le(40).all()
    assert result["mother_population"]["n"] == 427
    assert result["simple_rule_population"]["n"] == 119
    assert [item["feature"] for item in result["simple_conditions"]] == [
        "post_gap_freeze_corridor_float_turnover",
        "higher_low_share_10d",
    ]
    assert len(result["simple_conditions"]) <= 3
    assert frame.descriptive_rule_match.dtype == bool
    forbidden = ("pnl", "net_return", "gross_return", "trade_return")
    assert not any(any(token in column.lower() for token in forbidden) for column in frame.columns)
    assert pd.to_datetime(frame.causal_first_return).max() < pd.Timestamp("2021-01-01")
    assert result["audit"]["RETURN_ANALYSIS_RUN"] == "NO"
    assert result["audit"]["STRATEGY_BACKTEST_RUN"] == "NO"
    assert result["audit"]["PREDICTIVE_VALIDATION_RUN"] == "NO"
    assert result["audit"]["DATA_2021_OR_LATER_USED"] == "NO"
    assert result["audit"]["STRUCTURAL_PATH_AFTER_H40_USED_COUNT"] == 0


def test_chart_book_is_complete_and_marks_gap_and_outcome() -> None:
    index = pd.read_csv(research.CHART_INDEX)
    reader = PdfReader(str(research.PDF))
    assert len(index) == research.CHART_COUNT == 40
    assert int((~index.u_full_fill_20d).sum()) == 3
    assert len(reader.pages) == len(index) + 1
    page_sizes = {
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in reader.pages
    }
    assert len(page_sizes) == 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert text.count("true gap [L,U]") >= len(index)
    assert text.count("causal first return") >= len(index)
    assert "No entry, exit, cost, return, PnL, or predictive claim" in text
    assert "2021 and later are not used" in text
