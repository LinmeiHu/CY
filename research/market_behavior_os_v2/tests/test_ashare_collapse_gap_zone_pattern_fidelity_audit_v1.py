# ruff: noqa: E501
from __future__ import annotations

import json

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts.run_ashare_collapse_gap_zone_pattern_fidelity_audit_v1 import (
    AUDIT_MAPPING,
    BLIND_DIR,
    DEVELOPMENT_YEARS,
    RESULT,
    REVIEW_CSV,
    SAMPLE_MANIFEST,
    AuditError,
    assert_no_outcome_columns,
    detect_strict_gap_primitives,
    group_zone_stacks,
    persistence_bucket,
    select_blind_sample,
)


def daily_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 4,
            "trade_date": pd.bdate_range("2020-01-06", periods=4),
            "open": [10.0, 8.9, 9.1, 7.8],
            "low": [9.5, 8.5, 8.8, 7.5],
            "corporate_action_count": [0, 0, 0, 1],
            "history_valid": [True] * 4,
        }
    )


def test_strict_gap_is_action_safe_and_interval_orientation_is_correct() -> None:
    gaps = detect_strict_gap_primitives(daily_fixture())
    assert list(gaps.trade_date) == [pd.Timestamp("2020-01-07")]
    assert gaps.iloc[0].lower_boundary == 8.9
    assert gaps.iloc[0].upper_boundary == 9.5
    assert gaps.lower_boundary.lt(gaps.upper_boundary).all()


def test_open_at_or_above_previous_low_is_not_a_strict_gap() -> None:
    frame = daily_fixture().iloc[:2].copy()
    frame.loc[frame.index[1], "open"] = 9.5
    assert detect_strict_gap_primitives(frame).empty


def test_zone_stack_preserves_each_primitive_and_lineage() -> None:
    frame = pd.DataFrame(
        {
            "gap_primitive_id": ["P1", "P2"],
            "symbol": ["000001.SZ"] * 2,
            "gap_cal_idx": [100, 110],
            "gap_date": pd.to_datetime(["2020-01-06", "2020-01-20"]),
            "peak_date": pd.to_datetime(["2019-12-02", "2019-12-02"]),
            "peak_coord_high": [20.0, 20.0],
            "lower_coord": [12.0, 10.0],
            "upper_coord": [12.5, 10.5],
            "decline_to_gap": [0.4, 0.5],
        }
    )
    grouped = group_zone_stacks(frame, pd.Series(False, index=["P2"]))
    assert len(grouped) == 2
    assert grouped.gap_primitive_id.nunique() == 2
    assert grouped.collapse_episode_id.nunique() == 1
    assert grouped.primitive_count.eq(2).all()
    assert grouped.stack_lower.eq(10.0).all()
    assert grouped.stack_upper.eq(12.5).all()


def test_outcome_columns_cannot_enter_blind_sampling() -> None:
    with pytest.raises(AuditError):
        assert_no_outcome_columns(pd.DataFrame({"collapse_episode_id": ["x"], "future_return": [0.1]}))


def test_persistence_buckets_include_same_day_and_longer_cases() -> None:
    assert persistence_bucket(0) == "SAME_DAY"
    assert persistence_bucket(1) == "NEXT_DAY"
    assert persistence_bucket(2) == "SHORT_PERSISTENCE"
    assert persistence_bucket(8) == "MEDIUM_PERSISTENCE"
    assert persistence_bucket(20) == "LONG_PERSISTENCE"
    assert persistence_bucket(31) == "VERY_LONG"


def test_sample_stratification_is_deterministic() -> None:
    rows = []
    quotas = {
        ("MAIN", "BROAD_MACHINE_POSITIVE"): 48,
        ("MAIN", "IMMEDIATE_FAST_REENTRY"): 12,
        ("MAIN", "NEAR_MISS_CONTROL"): 12,
        ("CHINEXT", "BROAD_MACHINE_POSITIVE"): 32,
        ("CHINEXT", "IMMEDIATE_FAST_REENTRY"): 8,
        ("CHINEXT", "NEAR_MISS_CONTROL"): 8,
    }
    index = 0
    buckets = ["SAME_DAY", "NEXT_DAY", "SHORT_PERSISTENCE", "MEDIUM_PERSISTENCE", "LONG_PERSISTENCE", "VERY_LONG"]
    for (board, machine_class), count in quotas.items():
        for offset in range(count):
            index += 1
            rows.append(
                {
                    "collapse_episode_id": f"S{index:04d}",
                    "board": board,
                    "machine_class": machine_class,
                    "is_st": offset % 5 == 0,
                    "multi_layer": offset % 2 == 0,
                    "persistence_bucket": buckets[offset % len(buckets)],
                    "leader_metric_bucket": "STRONG" if offset % 2 else "MEDIUM",
                }
            )
    frame = pd.DataFrame(rows)
    first = select_blind_sample(frame)
    second = select_blind_sample(frame.sample(frac=1, random_state=7))
    assert list(first.collapse_episode_id) == list(second.collapse_episode_id)
    assert first.board.value_counts().to_dict() == {"MAIN": 72, "CHINEXT": 48}


def test_completed_package_is_blind_sealed_and_representation_complete() -> None:
    if not RESULT.is_file():
        return
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    mapping = pd.read_parquet(AUDIT_MAPPING)
    manifest = pd.read_parquet(SAMPLE_MANIFEST)
    review = pd.read_csv(REVIEW_CSV, keep_default_na=False)
    assert len(mapping) == len(manifest) == len(review) == 120
    assert mapping.board.value_counts().to_dict() == {"MAIN": 72, "CHINEXT": 48}
    assert mapping.is_st.any()
    assert mapping.multi_layer.any()
    assert {"SAME_DAY", "NEXT_DAY"} <= set(mapping.persistence_bucket)
    assert review.PRIMARY_LABEL.eq("").all()
    assert manifest.post_reentry_bars.eq(0).all()
    assert manifest.identity_fields_in_blind_metadata.eq(0).all()
    for row in mapping.itertuples(index=False):
        data = (BLIND_DIR / f"{row.audit_id}.png").read_bytes()
        assert row.symbol.encode() not in data
        assert pd.Timestamp(row.peak_date).strftime("%Y-%m-%d").encode() not in data
    assert DEVELOPMENT_YEARS == tuple(range(2014, 2022))
    assert result["audits"]["post_2021_outcome_read_count"] == 0
    assert result["audits"]["validation_opened"] is False
    assert result["audits"]["repository_2024_plus_data_opened"] is False
    assert result["status"] == {
        "audit_package_complete": True,
        "human_pattern_review_required": True,
        "strategy_backtest_run": False,
        "return_outcome_analysis_run": False,
    }
