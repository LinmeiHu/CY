# ruff: noqa: E501
from __future__ import annotations

import json
import math

import pandas as pd

from research.market_behavior_os_v2.scripts.run_ashare_collapse_defining_gap_zone_high_precision_pilot_v3 import (
    BLIND_DIR,
    CANDIDATES,
    DIAGNOSTIC_DIR,
    EXPECTED_SPEC_SHA256,
    MAPPING,
    RESULT,
    REVIEW_COLUMNS,
    REVIEW_CSV,
    load_chart_frame,
)


def split_values(value: object, separator: str = "|") -> list[str]:
    return str(value).split(separator)


def test_completed_v3_candidates_obey_collapse_first_semantics() -> None:
    candidates = pd.read_parquet(CANDIDATES)
    assert len(candidates) == 617
    assert candidates.symbol.nunique() > 1

    required_gates = [
        "persistence_pass",
        "fully_below_pass",
        "post_zone_depth_pass",
        "lower_regime_pass",
        "base_pass",
        "no_prior_partial_entry_pass",
        "unresolved_pass",
        "current_upward_entry",
    ]
    assert candidates[required_gates].all(axis=None)
    assert candidates.persistence_sessions.ge(10).all()
    assert candidates.prior_max_fully_below_run.ge(5).all()
    assert candidates.base_duration.ge(5).all()
    assert candidates.prior_partial_entry_count.eq(0).all()
    assert candidates.prior_full_fill_count.eq(0).all()
    assert candidates.coord_open.lt(candidates.zone_lower_boundary).all()
    assert candidates.coord_high.ge(candidates.zone_lower_boundary).all()
    assert candidates.prior_post_zone_low.le(candidates.zone_lower_boundary * 0.875).all()
    assert candidates.prior_min_rolling_median_close5.le(candidates.zone_lower_boundary * 0.925).all()
    assert candidates.minute_count.eq(241).all()
    assert candidates.distinct_minute_count.eq(241).all()
    assert candidates.candidate_reentry_date.le(pd.Timestamp("2021-12-31")).all()


def test_meaningful_layers_are_on_the_main_collapse_leg_and_significant() -> None:
    candidates = pd.read_parquet(CANDIDATES)
    for row in candidates.itertuples(index=False):
        dates = [pd.Timestamp(value) for value in split_values(row.meaningful_primitive_dates)]
        lowers = [float(value) for value in split_values(row.meaningful_primitive_lowers)]
        uppers = [float(value) for value in split_values(row.meaningful_primitive_uppers)]
        width_pcts = [float(value) for value in split_values(row.meaningful_primitive_width_pcts)]
        collapse_shares = [float(value) for value in split_values(row.meaningful_primitive_collapse_shares)]
        ids = split_values(row.meaningful_primitive_ids, ";")

        assert len(dates) == len(lowers) == len(uppers) == len(width_pcts) == len(collapse_shares) == len(ids)
        assert len(dates) == row.number_of_layers
        assert all(pd.Timestamp(row.peak_date) < date <= pd.Timestamp(row.postcollapse_low_date) for date in dates)
        assert all(upper > lower for lower, upper in zip(lowers, uppers, strict=True))
        assert all(width_pct >= 0.025 or collapse_share >= 0.08 for width_pct, collapse_share in zip(width_pcts, collapse_shares, strict=True))
        assert all(row.postcollapse_low_coord <= lower * 0.875 for lower in lowers)
        assert math.isclose(row.zone_lower_boundary, min(lowers), rel_tol=1e-11)
        assert row.target_primitive_id in ids


def test_primitive_lineage_is_complete_and_unambiguous() -> None:
    mapping = pd.read_parquet(MAPPING)
    for row in mapping.itertuples(index=False):
        meaningful_ids = split_values(row.meaningful_primitive_ids, ";")
        all_ids = split_values(row.all_primitive_ids, ";")
        all_dates = split_values(row.all_primitive_dates)
        all_lowers = split_values(row.all_primitive_lowers)
        all_uppers = split_values(row.all_primitive_uppers)
        all_flags = split_values(row.all_primitive_meaningful)
        assert len(all_ids) == len(all_dates) == len(all_lowers) == len(all_uppers) == len(all_flags)
        assert set(meaningful_ids) <= set(all_ids)
        assert all(value.startswith(f"{row.symbol}|") for value in all_ids)
        assert len(all_ids) == len(set(all_ids))


def test_blind_package_is_outcome_free_and_balanced_for_human_review() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    mapping = pd.read_parquet(MAPPING)
    review = pd.read_csv(REVIEW_CSV, keep_default_na=False)

    assert result["spec_sha256"] == EXPECTED_SPEC_SHA256
    assert result["input_identity"]["v2_human_labels_read"] is False
    assert result["input_identity"]["outcome_fields_read"] is False
    assert result["pilot"]["outcome_selected_sample_count"] == 0
    assert result["pilot"]["post_entry_bar_count"] == 0
    assert result["status"] == {
        "pilot_package_complete": True,
        "human_review_required": True,
        "return_analysis_run": False,
        "strategy_backtest_run": False,
    }
    assert len(mapping) == len(review) == 20
    assert mapping.symbol.nunique() == 20
    assert mapping.board.value_counts().to_dict() == {"MAIN": 13, "CHINEXT": 7}
    assert mapping.multi_layer.sum() == 10
    assert (~mapping.multi_layer).sum() == 10
    assert set(mapping.candidate_year) == set(range(2014, 2022))
    assert list(review.columns) == REVIEW_COLUMNS
    assert review.drop(columns="audit_id").eq("").all(axis=None)
    assert {path.name for path in BLIND_DIR.glob("V3_*.png")} == {f"V3_{index:03d}.png" for index in range(1, 21)}
    assert {path.name for path in DIAGNOSTIC_DIR.glob("V3_*.png")} == {f"V3_{index:03d}.png" for index in range(1, 21)}
    for row in mapping.itertuples(index=False):
        data = (BLIND_DIR / f"{row.audit_id}.png").read_bytes()
        assert row.symbol.encode() not in data
        assert pd.Timestamp(row.peak_date).strftime("%Y-%m-%d").encode() not in data


def test_chart_frame_ends_at_the_first_return_marker_without_future_bars() -> None:
    row = pd.read_parquet(MAPPING).sort_values("audit_id", kind="mergesort").iloc[0]
    frame = load_chart_frame(row)
    assert frame.trade_date.max() == pd.Timestamp(row.candidate_reentry_date)
    final = frame.iloc[-1]
    assert final.coord_open < row.zone_lower_boundary
    assert final.coord_high >= row.zone_lower_boundary
