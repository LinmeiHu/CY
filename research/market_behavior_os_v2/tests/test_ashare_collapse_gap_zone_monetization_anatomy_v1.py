# ruff: noqa: E501
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy,
)


@pytest.fixture(scope="module")
def events() -> pd.DataFrame:
    return pd.read_parquet(anatomy.EVENTS)


def _minute_row(when: str, cal_idx: int, open_: float, high: float) -> dict[str, object]:
    return {
        "bar_end_time": pd.Timestamp(when),
        "cal_idx": cal_idx,
        "open": open_,
        "coord_open": open_,
        "coord_high": high,
        "coordinate_factor": 1.0,
        "invalid_step_cum": 0.0,
        "history_valid": True,
        "current_valid": True,
        "hard_valid": True,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "market_rule_valid": True,
        "corporate_action_blocking": False,
        "down_limit_price": 8.0,
    }


def test_frozen_identity_and_common_cohort_are_exact(events: pd.DataFrame) -> None:
    anatomy.validate_inputs()
    source = pd.read_parquet(anatomy.SOURCE)
    canonical = pd.read_parquet(anatomy.outcome.ENTRIES).set_index("event_id")
    assert len(events) == len(source) == 538
    assert events.event_id.is_unique and source.event_id.is_unique
    assert source.primary_complete_60d.all()
    for column in ("entry_cal_idx", "entry_raw_price", "entry_coord_price"):
        left = source.set_index("event_id")[column].astype(float)
        right = canonical.loc[left.index, column].astype(float)
        assert np.allclose(left, right, rtol=0, atol=1e-12)


def test_t1_target_ignores_same_day_and_uses_u_or_better_open() -> None:
    path = pd.DataFrame(
        [
            _minute_row("2020-01-02 14:57", 10, 9.9, 10.5),
            _minute_row("2020-01-03 09:31", 11, 9.9, 10.1),
        ]
    )
    hit = anatomy.first_target(path, pd.Timestamp("2020-01-02"), 10, 10.0, 0.0)
    assert hit is not None
    assert hit.cal_idx == 11
    assert hit.target_raw_execution == pytest.approx(10.0)
    assert not hit.target_gap_above

    path.loc[1, ["open", "coord_open", "coord_high"]] = [10.2, 10.2, 10.3]
    gap = anatomy.first_target(path, pd.Timestamp("2020-01-02"), 10, 10.0, 0.0)
    assert gap is not None
    assert gap.target_raw_execution == pytest.approx(10.2)
    assert gap.target_gap_above


def test_target_before_loss_requires_strict_time_order() -> None:
    path = pd.DataFrame(
        {
            "bar_end_time": pd.to_datetime(["2020-01-03 09:31", "2020-01-03 09:32"]),
            "cal_idx": [11, 11],
            "invalid_step_cum": [0.0, 0.0],
            "coord_low": [8.9, 9.5],
        }
    )
    loss_time = anatomy.first_loss_time(path, 10.0, -0.10, 20, 0.0)
    assert loss_time == pd.Timestamp("2020-01-03 09:31")
    assert not (pd.Timestamp("2020-01-03 09:31") < loss_time)
    assert pd.Timestamp("2020-01-03 09:30") < loss_time


def test_generated_target_execution_and_winner_mae_are_causal(events: pd.DataFrame) -> None:
    assert events.legal_target_session_offset.dropna().ge(1).all()
    targeted = events.loc[events.legal_target_time.notna()]
    minutes = pd.read_parquet(anatomy.MINUTE_PATH)
    minutes["bar_end_time"] = pd.to_datetime(minutes.bar_end_time)
    nongap = targeted.loc[~targeted.legal_target_gap_above]
    target_bars = nongap[["event_id", "legal_target_time", "legal_target_raw_execution", "U"]].merge(
        minutes[["event_id", "bar_end_time", "coordinate_factor"]],
        left_on=["event_id", "legal_target_time"],
        right_on=["event_id", "bar_end_time"],
        how="left",
        validate="one_to_one",
    )
    assert np.allclose(
        target_bars.legal_target_raw_execution * target_bars.coordinate_factor,
        target_bars.U,
        rtol=0,
        atol=1e-9,
    )
    for row in targeted.head(12).itertuples(index=False):
        before = minutes.loc[
            minutes.event_id.eq(row.event_id)
            & minutes.bar_end_time.ge(pd.Timestamp(row.entry_time))
            & minutes.bar_end_time.lt(pd.Timestamp(row.legal_target_time))
            & minutes.invalid_step_cum.eq(float(row.peak_invalid_step_cum))
        ]
        expected = before.coord_low.min() / float(row.entry_coord_price) - 1
        assert row.mae_before_target == pytest.approx(expected)


def test_unresolved_transitions_and_date_equal_aggregation_are_exact(events: pd.DataFrame) -> None:
    unresolved20 = ~events.legal_full_fill_20d
    unresolved40 = ~events.legal_full_fill_40d
    result = json.loads(anatomy.RESULT.read_text(encoding="utf-8"))
    transitions = result["unresolved"]["transitions"]
    assert transitions["20_to_40"]["rate"] == pytest.approx(events.loc[unresolved20, "legal_full_fill_40d"].mean())
    assert transitions["20_to_60"]["rate"] == pytest.approx(events.loc[unresolved20, "legal_full_fill_60d"].mean())
    assert transitions["40_to_60"]["rate"] == pytest.approx(events.loc[unresolved40, "legal_full_fill_60d"].mean())
    fixture = pd.DataFrame(
        {"reentry_date": pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03"]), "metric": [1.0, 3.0, 10.0]}
    )
    summary = anatomy.date_equal_stats(fixture, "metric")
    assert summary["n"] == 2
    assert summary["mean"] == pytest.approx(6.0)
    assert summary["median"] == pytest.approx(6.0)


def test_full_or_payoffs_and_horizon_validity_are_deterministic(events: pd.DataFrame) -> None:
    for horizon in anatomy.HORIZONS:
        valid = events[f"full_or_h{horizon}_valid"]
        assert events.loc[valid, f"full_or_h{horizon}_net"].notna().all()
        assert events.loc[~valid, f"full_or_h{horizon}_net"].isna().all()
        target = events.loc[events[f"full_or_h{horizon}_exit_kind"].eq("TARGET")]
        no_cash = target.loc[~target.symbol.isin(pd.read_parquet(anatomy.strategy.ACTION_EVENTS).symbol.unique())]
        expected = no_cash.legal_target_raw_execution * (1 - anatomy.COST) / (no_cash.entry_raw_price * (1 + anatomy.COST)) - 1
        assert np.allclose(expected, no_cash[f"full_or_h{horizon}_net"], rtol=0, atol=1e-12)


def test_year_boundary_censor_and_sealed_outcome_boundaries_hold(events: pd.DataFrame) -> None:
    bounds = pd.read_parquet(anatomy.BOUNDS)
    daily = pd.read_parquet(anatomy.DAILY_PATH, columns=["trade_date"])
    minutes = pd.read_parquet(anatomy.MINUTE_PATH, columns=["trade_date"])
    assert len(bounds) == 538
    assert (bounds.path_end_cal_idx - bounds.entry_cal_idx).eq(60).all()
    assert pd.to_datetime(bounds.path_end_date).max() <= pd.Timestamp("2021-12-31")
    assert pd.to_datetime(daily.trade_date).max() <= pd.Timestamp("2021-12-31")
    assert pd.to_datetime(minutes.trade_date).max() <= pd.Timestamp("2021-12-31")
    assert events.entry_year.between(2014, 2021).all()


def test_correctness_audit_is_zero_and_validation_is_sealed() -> None:
    result = json.loads(anatomy.RESULT.read_text(encoding="utf-8"))
    assert all(value == 0 for value in result["audit"].values())
    assert result["validation_opened"] is False
    assert result["repository_2024_plus_data_opened"] is False
    assert math.isclose(result["event_weighted"]["legal_fill_curve"]["60d"]["rate"], 473 / 538)
