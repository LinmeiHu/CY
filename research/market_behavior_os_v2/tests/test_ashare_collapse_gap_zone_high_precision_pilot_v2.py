# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json

import pandas as pd

from research.market_behavior_os_v2.scripts.run_ashare_collapse_gap_zone_high_precision_pilot_v2 import (
    AUDIT_MAPPING,
    BLIND_DIR,
    CANDIDATE_POOL,
    EXPECTED_SPEC_SHA256,
    RESULT,
    REVIEW_CSV,
    SAMPLE_MANIFEST,
    SPEC,
    identity_leak_count,
    select_sample,
)


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_spec_is_frozen_and_explicitly_stops_v1_review() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert sha256(SPEC) == EXPECTED_SPEC_SHA256
    assert spec["supersedes_review_workflow"]["v1_review_status"] == "STOPPED_INCOMPLETE_BY_AUTHORIZATION"
    assert spec["supersedes_review_workflow"]["finish_v1_review_requested"] is False
    assert spec["supersedes_review_workflow"]["v1_partial_labels_read_or_summarized"] is False
    assert spec["forbidden"][-3:] == [
        "2022-2023 repository data",
        "2024+ repository data",
        "return-trained ML",
    ]


def test_candidate_pool_satisfies_every_high_precision_gate() -> None:
    pool = pd.read_parquet(CANDIDATE_POOL)
    assert len(pool) >= 30
    assert pool.symbol.nunique() == len(pool)
    assert pool.board_relative_return_percentile.ge(0.90).all()
    assert pool.max_runup_from_60_low.ge(0.50).all()
    assert pool.return60_into_peak.ge(0.30).all()
    assert pool.main_rise_duration.between(5, 80).all()
    assert pool.rise_speed.ge(0.01).all()
    assert pool.number_large_up_days.ge(3).all()
    assert pool.decline_to_gap.ge(0.30).all()
    assert pool.peak_to_gap_sessions.between(1, 40).all()
    assert pool.return5_into_gap.le(-0.08).all()
    assert pool.width_pct_vs_prev_close.ge(0.02).all()
    assert pool.candidate_session_lag_from_final_layer.between(6, 250).all()
    assert pool.depth_below_zone.ge(0.125).all()
    assert pool.candidate_coord_open.lt(pool.lower_coord).all()
    assert pool.minute_count.eq(241).all()
    assert pool.distinct_minute_count.eq(241).all()


def test_sample_is_deterministic_unique_and_board_preserving() -> None:
    pool = pd.read_parquet(CANDIDATE_POOL)
    first = select_sample(pool)
    second = select_sample(pool.sample(frac=1, random_state=17))
    assert first.collapse_episode_id.tolist() == second.collapse_episode_id.tolist()
    assert first.board.value_counts().to_dict() == {"MAIN": 20, "CHINEXT": 10}
    assert len(first) == first.symbol.nunique() == 30
    assert first.multi_layer.any()


def test_blind_package_has_no_identity_date_or_post_marker_leak() -> None:
    mapping = pd.read_parquet(AUDIT_MAPPING)
    manifest = pd.read_parquet(SAMPLE_MANIFEST)
    assert len(mapping) == len(manifest) == 30
    assert len(list(BLIND_DIR.glob("HP_*.png"))) == 30
    assert identity_leak_count(mapping) == 0
    assert manifest.post_reentry_bars.eq(0).all()
    assert manifest.identity_fields_in_blind_metadata.eq(0).all()
    assert manifest.chart_end_time.astype("datetime64[ns]").equals(mapping.candidate_reentry_time.astype("datetime64[ns]"))


def test_new_review_is_blank_and_outcomes_are_absent() -> None:
    mapping = pd.read_parquet(AUDIT_MAPPING)
    review = pd.read_csv(REVIEW_CSV, keep_default_na=False)
    forbidden = ("post_reentry", "future_", "t1_return", "t3_return", "mfe", "mae", "winner", "sharpe", "calmar", "cagr", "outcome")
    assert len(review) == 30
    assert all(review[column].eq("").all() for column in review.columns if column != "audit_id")
    assert not [column for column in mapping if any(token in column.lower() for token in forbidden)]


def test_result_preserves_seals_and_stops_at_human_gate() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["candidate_pool"] == {
        "rows": 34,
        "symbols": 34,
        "main": 24,
        "chinext": 10,
        "layered": 20,
        "first_candidate_date": "2014-08-14",
        "last_candidate_date": "2021-11-23",
    }
    assert result["sample"]["blind_chart_count"] == 30
    assert result["sample"]["nonblank_human_label_count"] == 0
    assert result["governance"] == {
        "post_2021_outcome_read_count": 0,
        "validation_opened": False,
        "repository_2024_plus_data_opened": False,
        "strategy_backtest_run": False,
        "return_outcome_analysis_run": False,
    }
    assert result["status"]["v1_review_workflow_stopped"] is True
    assert result["status"]["human_pattern_review_required"] is True
