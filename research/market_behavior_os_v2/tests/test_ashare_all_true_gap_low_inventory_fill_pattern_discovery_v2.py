from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from research.market_behavior_os_v2.scripts import (
    run_ashare_all_true_gap_low_inventory_fill_pattern_discovery_v2 as research,
)


def test_contract_starts_from_direct_all_gap_population() -> None:
    contract = json.loads(Path(research.CONTRACT).read_text(encoding="utf-8"))
    source = contract["source_population"]
    assert source["construction"] == (
        "directly from governed PIT daily rows; no V6/V8 candidate input"
    )
    assert source["v6_core_required"] is False
    assert source["collapse_leg_required"] is False
    assert source["primary_gap_hierarchy_required"] is False
    assert source["memory_class_required"] is False
    assert contract["chronology"]["2021_and_later_used"] is False
    assert contract["stage_b_structural_outcome"]["return_or_pnl_opened"] is False


def test_all_gap_primitive_and_stage_a_population_are_causal() -> None:
    gaps = pd.read_parquet(research.ALL_GAPS)
    mother = pd.read_parquet(research.STAGE_A_LEDGER)
    assert len(gaps) == 88_785
    assert gaps.gap_id.is_unique
    assert gaps.W.gt(0).all()
    assert gaps.gap_width_pct.gt(0).all()
    assert pd.to_datetime(gaps.gap_date).max() < pd.Timestamp("2021-01-01")
    assert len(mother) == 2_209
    assert mother.gap_id.is_unique
    assert mother.gap_width_pct.ge(research.MIN_TRUE_GAP_WIDTH_PCT).all()
    assert mother.gap_age_sessions.ge(research.MIN_FULLY_BELOW_SESSIONS + 1).all()
    assert mother.minute_history_sessions.eq(research.PRE_GAP_SESSIONS).all()
    assert mother.exact_241_minute_sessions.eq(research.PRE_GAP_SESSIONS).all()
    assert mother.first_return_session_minutes.eq(241).all()
    assert mother.pre_gap_inside_density_relative_local.le(research.MAX_INSIDE_DENSITY).all()
    assert mother.pre_gap_corridor_density_relative_local.le(research.MAX_CORRIDOR_DENSITY).all()
    assert pd.to_datetime(mother.first_return_date).max() < pd.Timestamp("2021-01-01")
    outcome_like = [
        column
        for column in mother.columns
        if any(
            token in column.lower()
            for token in ("u_fill", "return_label", "pnl", "profit", "win")
        )
    ]
    assert outcome_like == []


def test_simple_description_and_outcome_horizon_are_frozen() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    ledger = pd.read_parquet(research.DISCOVERY_LEDGER)
    assert result["source_population"]["v6_core_required"] is False
    assert result["mother_population"]["n"] == 2_209
    assert result["simple_rule_population"]["n"] == 305
    assert [condition["feature"] for condition in result["simple_conditions"]] == [
        "gap_width_pct",
        "pre_gap_inside_density_relative_local",
    ]
    assert ledger.u_fill_offset.dropna().le(40).all()
    assert int(ledger.descriptive_rule_match.sum()) == 305
    assert result["audit"]["V6_CORE_CANDIDATE_GATE_USED"] == "NO"
    assert result["audit"]["PRE_PERSISTENCE_TOUCH_RESET_AS_FIRST_RETURN_COUNT"] == 0
    assert result["audit"]["RETURN_ANALYSIS_RUN"] == "NO"
    assert result["audit"]["DATA_2021_OR_LATER_USED"] == "NO"


def test_pdf_contains_every_final_match_and_is_uniform() -> None:
    index = pd.read_csv(research.CHART_INDEX)
    reader = PdfReader(str(research.PDF))
    assert len(index) == 305
    assert index.gap_id.is_unique
    assert len(reader.pages) == len(index) + 1
    page_sizes = {
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in reader.pages
    }
    assert len(page_sizes) == 1
    first_page = reader.pages[0].extract_text() or ""
    assert "no V6 CORE gate" in first_page
    assert "The following 305 pages include every final condition match" in first_page
    assert "2021 and later are unused" in first_page
