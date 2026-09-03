from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_clean_fracture_first_return_semantic_v8 as research,
)


def test_contract_is_outcome_blind_and_uses_strict_clean_fracture_semantics() -> None:
    contract = research.contract_value()
    retrieval = contract["retrieval_contract"]
    assert contract["scientific_status"] == "OUTCOME_BLIND_SEMANTIC_RETRIEVAL_PILOT_NOT_A_STRATEGY"
    assert retrieval["main_collapse_leg"]["duration_sessions_inclusive_bounds"] == [60, 120]
    assert retrieval["main_collapse_leg"]["minimum_peak_to_gap_sessions"] == 60
    assert retrieval["raw_inventory"]["turnover_decay_used"] is False
    assert retrieval["pristine_return"]["clock_reset"] is False
    assert retrieval["pristine_return"]["attack_2"] == "NOT_PART_OF_THIS_SEMANTIC_PILOT"
    assert contract["governance"]["return_analysis_run"] is False
    assert contract["governance"]["strategy_backtest_run"] is False
    assert contract["governance"]["repository_2024_plus_data_opened"] is False


def test_retained_population_fails_closed_on_every_semantic_gate() -> None:
    ledger = pd.read_parquet(research.SEMANTIC_LEDGER)
    retained = ledger.loc[ledger.retained_clean_fracture]
    gate_columns = [column for column in ledger.columns if column.startswith("gate_")]
    assert len(ledger) == 3063
    assert len(retained) == 17
    assert retained.symbol.nunique() == 17
    assert retained[gate_columns].notna().all().all()
    assert retained[gate_columns].all().all()
    assert retained.peak_to_gap_sessions.min() >= 60
    assert retained.collapse_leg_duration_sessions.between(60, 120).all()
    assert retained.pre_gap_inside_touch_sessions.max() <= 4
    assert retained.pre_gap_corridor_touch_sessions.max() <= 8
    assert retained.post_gap_corridor_approach_sessions.max() == 0
    assert retained.causal_first_return.gt(retained.cluster_freeze_time).all()
    assert retained.causal_first_return.max() < pd.Timestamp("2022-01-01")


def test_blind_pilot_has_frozen_mix_and_does_not_leak_identity() -> None:
    key = pd.read_parquet(research.SEALED_KEY)
    blind = pd.read_csv(research.BLIND_INDEX)
    review = pd.read_csv(research.REVIEW, keep_default_na=False)
    assert len(key) == len(blind) == len(review) == 30
    assert key.candidate_id.nunique() == 30
    assert key.symbol.nunique() == 30
    assert key.board.value_counts().to_dict() == {"MAIN": 20, "CHINEXT": 10}
    expected = {
        (category, board): count
        for category, boards in research.SAMPLE_QUOTAS.items()
        for board, count in boards.items()
        if count
    }
    observed = key.groupby(["blind_pool", "board"]).size().to_dict()
    assert observed == expected
    assert list(blind.columns) == ["chart_id", "post_event_bars", "chart_file"]
    assert not {"candidate_id", "symbol", "blind_pool", "gap_id"}.intersection(blind.columns)
    assert blind.post_event_bars.sum() == 0
    assert review.drop(columns="chart_id").eq("").all().all()


def test_pdf_is_complete_and_contains_no_sealed_identity() -> None:
    reader = PdfReader(str(research.PDF))
    assert len(reader.pages) == 30
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for forbidden in ("candidate_id", "RETAINED_CLEAN", "REJECTED_", "net return", "PnL"):
        assert forbidden not in text
    assert text.count("L = ") == 30
    assert text.count("U = ") == 30
    assert text.count("gap formation") >= 30


def test_machine_result_records_zero_outcome_activity() -> None:
    result = json.loads(Path(research.RESULT).read_text(encoding="utf-8"))
    audit = result["audit"]
    assert result["status"] == "STOPPED_FOR_HUMAN_BLIND_REVIEW"
    assert result["coverage"]["retained_clean_fracture"] == 17
    assert result["blind_pilot"]["chart_count"] == 30
    assert audit["RETURN_ANALYSIS_RUN"] == "NO"
    assert audit["STRATEGY_BACKTEST_RUN"] == "NO"
    assert audit["REPOSITORY_2024_PLUS_DATA_OPENED"] == "NO"
    assert audit["POST_EVENT_CHART_BAR_COUNT"] == 0
    assert audit["MISSING_REQUIRED_HISTORY_PASSED_COUNT"] == 0
    assert audit["PRIOR_NEAR_TOUCH_PASSED_COUNT"] == 0
