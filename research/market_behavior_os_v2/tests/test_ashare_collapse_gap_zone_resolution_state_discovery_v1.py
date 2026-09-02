# ruff: noqa: E501
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_resolution_state_discovery_v1 as discovery,
)


@pytest.fixture(scope="module")
def source() -> pd.DataFrame:
    return pd.read_parquet(discovery.SOURCE)


@pytest.fixture(scope="module")
def states() -> pd.DataFrame:
    return pd.read_parquet(discovery.STATES)


@pytest.fixture(scope="module")
def result() -> dict[str, object]:
    return json.loads(discovery.RESULT.read_text(encoding="utf-8"))


def _minute_row(when: str, cal_idx: int, high: float) -> dict[str, object]:
    return {
        "bar_end_time": pd.Timestamp(when),
        "cal_idx": cal_idx,
        "open": 9.9,
        "coord_open": 9.9,
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


def test_frozen_detector_primary_layer_and_e1_identity(source: pd.DataFrame) -> None:
    discovery.validate_inputs()
    frozen = pd.read_parquet(discovery.outcome.EVENTS).set_index("event_id")
    canonical = pd.read_parquet(discovery.outcome.ENTRIES).set_index("event_id")
    assert len(frozen) == 617
    assert len(source) == 598 and source.event_id.is_unique
    assert source.executable_entry.all()
    indexed = source.set_index("event_id")
    for column in ("primary_layer_id", "L", "U", "W"):
        left = indexed[column]
        right = frozen.loc[left.index, column]
        if pd.api.types.is_numeric_dtype(left):
            assert np.allclose(left, right, rtol=0, atol=1e-12)
        else:
            assert left.equals(right)
    for column in ("entry_cal_idx", "entry_raw_price", "entry_coord_price", "entry_invalid_step_cum"):
        assert np.allclose(indexed[column], canonical.loc[indexed.index, column], rtol=0, atol=1e-12)
    assert source.risk_blocked_entry.sum() == 4


def test_checkpoint_clocks_dynamic_cohorts_and_outcomes_are_strict(states: pd.DataFrame, result: dict[str, object]) -> None:
    assert set(states.checkpoint.unique()) == set(discovery.CHECKPOINTS)
    assert (states.checkpoint_cal_idx - states.entry_cal_idx).eq(states.checkpoint).all()
    assert pd.to_datetime(states.checkpoint_time).dt.hour.eq(15).all()
    assert pd.to_datetime(states.checkpoint_time).dt.minute.eq(0).all()
    targeted = states.loc[states.legal_target_time.notna()]
    assert (pd.to_datetime(targeted.legal_target_time) > pd.to_datetime(targeted.checkpoint_time)).all()
    assert targeted.legal_target_offset.gt(targeted.checkpoint).all()
    assert states.loc[states.future_sessions_to_u.notna(), "future_sessions_to_u"].gt(0).all()
    for checkpoint in discovery.CHECKPOINTS:
        recon = result["checkpoint_reconciliation"][f"D{checkpoint}"]
        assert sum(value for key, value in recon.items() if key != "source_post_entry_eligible") == 594
        assert recon["active_unresolved"] == int(states.checkpoint.eq(checkpoint).sum())
        for horizon in discovery.HORIZONS:
            if checkpoint >= horizon:
                assert not states.loc[states.checkpoint.eq(checkpoint), f"resolve_by_d{horizon}_eligible"].any()


def test_same_day_structural_hit_is_not_a_legal_target() -> None:
    path = pd.DataFrame(
        [
            _minute_row("2020-01-02 14:57", 10, 10.5),
            _minute_row("2020-01-03 09:31", 11, 10.1),
        ]
    )
    target = discovery.first_target(path, 10, 10.0, 0.0)
    assert target is not None
    assert target.cal_idx == 11
    assert target.bar_end_time == pd.Timestamp("2020-01-03 09:31")


def test_frozen_state_arithmetic_and_bins() -> None:
    state_path = pd.DataFrame({"coord_high": [10.4, 10.6, 10.2], "coord_low": [9.4, 9.0, 9.3]})
    closes = pd.DataFrame({"coord_close": [9.8, 10.2, 9.5]})
    values = discovery.compute_state_values(
        state_path,
        closes,
        lower=10.0,
        width=1.0,
        entry_price=10.0,
        target_gross_distance=0.04,
    )
    assert values["max_progress"] == pytest.approx(0.6)
    assert values["current_zone"] == pytest.approx(-0.5)
    assert values["distance"] == pytest.approx(0.5)
    assert values["mae"] == pytest.approx(-0.1)
    assert values["arr"] == pytest.approx(2.5)
    assert values["recovery"] == pytest.approx(0.5)
    assert values["underwater"] == pytest.approx(2 / 3)
    assert values["below_l"] == pytest.approx(2 / 3)
    bins = discovery.state_bins(values["max_progress"], values["distance"], values["arr"], values["recovery"], values["underwater"], -0.3)
    assert bins == {"progress_bin": "P1", "distance_bin": "Z1", "arr_bin": "A2", "recovery_bin": "R1", "underwater_bin": "MID", "recovery_3d_state": "DOWN"}


def test_fs_definitions_are_exact(states: pd.DataFrame) -> None:
    assert states.fs1.eq((states.max_progress_raw < 0.25) & (states.adverse_reward_ratio >= 2)).all()
    assert states.fs2.eq((states.distance_below_l_w > 1) & (states.recovery_to_l < 1 / 3)).all()
    expected_fs3 = (states.max_progress_raw < 0.25) & (states.adverse_reward_ratio >= 2) & states.recovery_3d_w.lt(-0.25)
    assert states.fs3.eq(expected_fs3).all()


def test_date_equal_aggregation_is_not_event_weighted() -> None:
    fixture = pd.DataFrame(
        {"reentry_date": pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03"]), "label": [0, 1, 1]}
    )
    summary = discovery.date_equal(fixture, "label", "reentry_date")
    assert summary["dates"] == 2
    assert summary["probability"] == pytest.approx(0.75)


def test_2021_boundary_qd010_and_sealed_periods(source: pd.DataFrame, states: pd.DataFrame, result: dict[str, object]) -> None:
    bounds = pd.read_parquet(discovery.BOUNDS)
    daily_dates = pd.read_parquet(discovery.DAILY_PATH, columns=["trade_date"])
    minute_dates = pd.read_parquet(discovery.MINUTE_PATH, columns=["trade_date"])
    assert source.entry_year.between(2014, 2021).all()
    assert pd.to_datetime(bounds.path_end_date).max() <= pd.Timestamp("2021-12-31")
    assert pd.to_datetime(daily_dates.trade_date).max() <= pd.Timestamp("2021-12-31")
    assert pd.to_datetime(minute_dates.trade_date).max() <= pd.Timestamp("2021-12-31")
    blocked = set(source.loc[source.risk_blocked_entry, "event_id"])
    assert blocked and blocked.isdisjoint(set(states.event_id))
    assert result["audit"]["post_2021_outcome_read_count"] == 0
    assert result["validation_opened"] is False
    assert result["repository_2024_plus_data_opened"] is False


def test_all_correctness_audits_are_zero(result: dict[str, object]) -> None:
    assert all(value == 0 for value in result["audit"].values())
    assert result["verdict"] == "ZONE_TAIL_RISK_ONLY_DETECTABLE_AFTER_DAMAGE"
