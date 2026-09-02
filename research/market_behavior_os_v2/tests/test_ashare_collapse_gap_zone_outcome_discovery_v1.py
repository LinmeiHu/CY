# ruff: noqa: E501
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts.run_ashare_collapse_gap_zone_outcome_discovery_v1 import (
    EVENTS,
    EXPECTED_SPEC_SHA256,
    EXPECTED_V3,
    MINUTE_PATH,
    RESULT,
    SPEC,
    date_equal,
    v1,
)


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return pd.read_parquet(EVENTS)


@pytest.fixture(scope="module")
def minutes() -> pd.DataFrame:
    frame = pd.read_parquet(MINUTE_PATH)
    frame["bar_end_time"] = pd.to_datetime(frame.bar_end_time)
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def test_frozen_v3_detector_and_spec_identity_are_unchanged() -> None:
    assert v1.sha256_file(SPEC) == EXPECTED_SPEC_SHA256
    for path, digest in EXPECTED_V3.items():
        assert v1.sha256_file(path) == digest


def test_primary_layer_is_the_frozen_lowest_meaningful_layer(events: pd.DataFrame) -> None:
    assert len(events) == 617
    assert events.event_id.is_unique
    assert events.W.gt(0).all()
    for row in events.itertuples(index=False):
        ids = str(row.meaningful_primitive_ids).split(";")
        lowers = [float(value) for value in str(row.meaningful_primitive_lowers).split("|")]
        assert row.primary_layer_id == row.target_primitive_id
        assert row.primary_layer_id in ids
        assert math.isclose(row.L, min(lowers), rel_tol=1e-10)
        assert pd.Timestamp(row.zone_formation_date) <= pd.Timestamp(row.postcollapse_low_date)


def test_first_lower_return_and_acceptance_bar_are_causal(events: pd.DataFrame, minutes: pd.DataFrame) -> None:
    joined = minutes.merge(
        events[["event_id", "L", "first_lower_return_time", "acceptance_time"]],
        on="event_id", how="left", validate="many_to_one",
    )
    anchors = joined.loc[joined.bar_end_time.eq(pd.to_datetime(joined.first_lower_return_time))]
    assert anchors.event_id.nunique() == 617
    assert anchors.lineage_valid.all()
    assert anchors.coord_high.ge(anchors.L).all()
    accepted = joined.loc[joined.acceptance_time.notna()]
    confirmation = accepted.loc[accepted.bar_end_time.eq(pd.to_datetime(accepted.acceptance_time))]
    assert confirmation.event_id.nunique() == 611
    assert confirmation.coord_close.ge(confirmation.L).all()
    prior = accepted.loc[
        accepted.bar_end_time.ge(pd.to_datetime(accepted.first_lower_return_time))
        & accepted.bar_end_time.lt(pd.to_datetime(accepted.acceptance_time))
        & accepted.lineage_valid & accepted.coord_close.ge(accepted.L)
    ]
    assert prior.empty


def test_entry_uses_first_subsequent_legal_minute_and_jump_through_is_separate(events: pd.DataFrame, minutes: pd.DataFrame) -> None:
    joined = minutes.merge(
        events[["event_id", "acceptance_time", "entry_time"]],
        on="event_id", how="left", validate="many_to_one",
    )
    legal = (
        joined.lineage_valid & joined.history_valid & joined.current_valid & joined.hard_valid
        & joined.trade_status.eq(1) & joined.current_day_data_tradable
        & joined.market_rule_valid & ~joined.corporate_action_blocking
        & (np.round(joined.open * 100) < np.round(joined.up_limit_price * 100))
    )
    skipped = joined.loc[
        joined.entry_time.notna()
        & joined.bar_end_time.gt(pd.to_datetime(joined.acceptance_time))
        & joined.bar_end_time.lt(pd.to_datetime(joined.entry_time))
        & legal
    ]
    assert skipped.empty
    entered = events.loc[events.entry_time.notna()]
    assert entered.entry_time.gt(entered.acceptance_time).all()
    assert events.jumped_through_primary_layer.sum() == 13
    assert (~events.loc[events.jumped_through_primary_layer, "executable_entry"]).all()
    assert events.executable_entry.sum() == 598


def test_full_fill_boundary_and_multilayer_progression_preserve_layer_order(events: pd.DataFrame, minutes: pd.DataFrame) -> None:
    filled = events.loc[events.structural_first_full_fill_time.notna()]
    for row in filled.itertuples(index=False):
        path = minutes.loc[
            minutes.event_id.eq(row.event_id)
            & minutes.lineage_valid
            & minutes.bar_end_time.ge(pd.Timestamp(row.first_lower_return_time))
            & minutes.bar_end_time.le(pd.Timestamp(row.structural_first_full_fill_time))
        ].sort_values("bar_end_time", kind="mergesort")
        assert path.iloc[-1].coord_high >= row.U
        assert path.iloc[:-1].coord_high.lt(row.U).all()
    multi = events.loc[events.number_of_layers.gt(1)]
    assert len(multi) == 97
    for row in multi.itertuples(index=False):
        lowers = [float(value) for value in str(row.meaningful_primitive_lowers).split("|")]
        assert math.isclose(row.L, min(lowers), rel_tol=1e-10)
        assert row.meaningful_layers_reached_20d >= 1 or pd.isna(row.meaningful_layers_reached_20d)


def test_t1_same_day_target_is_never_sellable_and_date_equal_is_exact(events: pd.DataFrame) -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["summary"]["t1_constraint"]["target_realizable_same_day"] is False
    assert result["audits"]["t1_same_day_sell_violation_count"] == 0
    fixture = pd.DataFrame({
        "reentry_date": pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03"]),
        "metric": [1.0, 3.0, 10.0],
    })
    summary = date_equal(fixture, "metric")
    assert summary == {"dates": 2, "mean": 6.0, "median": 6.0}
    actual = events[["reentry_date", "t5_close_net"]].dropna().groupby("reentry_date").t5_close_net.mean().mean()
    reported = result["summary"]["reentry_date_equal"]["net_returns"]["t5_close"]["mean"]
    assert math.isclose(actual, reported, rel_tol=1e-14)


def test_sealed_boundaries_and_corporate_action_coordinates_hold(events: pd.DataFrame, minutes: pd.DataFrame) -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert minutes.trade_date.max() <= pd.Timestamp("2021-12-31")
    entered = events.loc[events.entry_time.notna()]
    assert entered.entry_invalid_step_cum.eq(entered.peak_invalid_step_cum).all()
    required_zero = [
        "detector_changed_after_outcome_open_count",
        "detector_uses_post_reentry_data_count",
        "entry_uses_future_bar_count",
        "primary_layer_changed_after_outcome_count",
        "postcollapse_local_gap_used_as_primary_layer_count",
        "duplicate_zone_entry_count",
        "corporate_action_coordinate_violation_count",
        "t1_same_day_sell_violation_count",
        "post_2021_outcome_read_count",
        "v3_anchor_mismatch_count",
        "acceptance_prior_qualifying_bar_count",
        "entry_skipped_legal_minute_count",
        "v3_anchor_session_not_241_count",
        "minute_path_post_2021_row_count",
    ]
    assert all(result["audits"][field] == 0 for field in required_zero)
    assert result["audits"]["validation_opened"] is False
    assert result["audits"]["repository_2024_plus_data_opened"] is False
