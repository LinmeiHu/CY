# ruff: noqa: E501
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_entry_quality_discovery_v1 as discovery,
)


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return pd.read_parquet(discovery.FEATURES)


@pytest.fixture(scope="module")
def result() -> dict[str, object]:
    return json.loads(discovery.RESULT.read_text(encoding="utf-8"))


def test_frozen_detector_layer_and_e1_identity(features: pd.DataFrame) -> None:
    discovery.validate_hashes({**discovery.FEATURE_INPUTS, **discovery.OUTCOME_INPUTS})
    source = pd.read_parquet(discovery.outcome.SOURCE_EVENTS).set_index("event_id")
    entries = pd.read_parquet(discovery.outcome.ENTRIES).set_index("event_id")
    indexed = features.set_index("event_id")
    assert len(source) == 617
    assert len(features) == 538 and features.event_id.is_unique
    for column in ("primary_layer_id", "L", "U", "W"):
        left, right = indexed[column], source.loc[indexed.index, column]
        if pd.api.types.is_numeric_dtype(left):
            assert np.allclose(left, right, rtol=0, atol=1e-12)
        else:
            assert left.equals(right)
    for column in ("entry_cal_idx",):
        assert np.allclose(indexed[column], entries.loc[indexed.index, column], rtol=0, atol=1e-12)
    assert (pd.to_datetime(features.entry_time) > pd.to_datetime(features.acceptance_time)).all()


def test_daily_feature_cutoff_is_strictly_before_signal_session(features: pd.DataFrame) -> None:
    daily = pd.read_parquet(discovery.PREENTRY_DAILY)
    cutoff = features.set_index("event_id").signal_cal_idx.astype(int)
    assert daily.cal_idx.lt(daily.event_id.map(cutoff)).all()
    assert pd.to_datetime(daily.available_at).le(pd.to_datetime(daily.decision_at)).all()
    assert pd.to_datetime(daily.trade_date).max() <= pd.Timestamp("2021-12-30")


def test_contact_features_use_exact_completed_signal_bar(features: pd.DataFrame) -> None:
    acceptance = pd.read_parquet(discovery.outcome.ACCEPTANCE).set_index("event_id")
    indexed = features.set_index("event_id")
    bars = acceptance.loc[indexed.index]
    coord_close = bars.acceptance_coord_close.astype(float)
    expected_penetration = (coord_close - indexed.L) / indexed.W
    assert np.allclose(indexed.contact_penetration, expected_penetration, rtol=0, atol=1e-12)
    expected_return = bars.close / bars.open - 1
    assert np.allclose(indexed.contact_bar_return, expected_return, rtol=0, atol=1e-12)
    valid = bars.high.gt(bars.low)
    expected_location = (bars.loc[valid, "close"] - bars.loc[valid, "low"]) / (bars.loc[valid, "high"] - bars.loc[valid, "low"])
    assert np.allclose(indexed.loc[valid, "contact_close_location"], expected_location, rtol=0, atol=1e-12)
    assert indexed.loc[~valid, "contact_close_location"].isna().all()


def test_path_efficiency_pullback_and_higher_low_definitions() -> None:
    rising = np.arange(1.0, 11.0)
    assert discovery.path_efficiency(rising) == pytest.approx(1.0)
    noisy = np.array([1.0, 2.0, 1.5])
    assert discovery.path_efficiency(noisy) == pytest.approx(0.5 / 1.5)
    closes = np.array([8.0, 8.5, 8.2, 8.8, 8.6, 9.0, 8.7, 9.2, 9.0, 9.5])
    running_peak = np.maximum.accumulate(closes)
    expected = np.max((running_peak - closes) / running_peak) / (10.0 / closes.min() - 1)
    assert discovery.pullback_burden(closes, 10.0) == pytest.approx(expected)
    assert discovery.higher_low(np.array([7, 8, 8, 9, 9, 8, 9, 9, 10, 10], dtype=float)) == "HIGHER_LOW"
    assert discovery.higher_low(np.array([8, 8, 9, 9, 9, 7, 8, 9, 9, 10], dtype=float)) == "LOWER_LOW"


def test_zone_age_and_authoritative_turnover_are_exact(features: pd.DataFrame) -> None:
    source = pd.read_parquet(discovery.SOURCE).set_index("event_id")
    indexed = features.set_index("event_id")
    expected_age = source.signal_cal_idx.astype(int) - source.zone_formation_cal_idx.astype(int)
    assert indexed.zone_age_sessions.equals(expected_age)
    daily = pd.read_parquet(discovery.PREENTRY_DAILY)
    for event_id in features.event_id.iloc[::107]:
        row = source.loc[event_id]
        path = daily.loc[daily.event_id.eq(event_id) & daily.cal_idx.between(int(row.zone_formation_cal_idx) + 1, int(row.signal_cal_idx) - 1)]
        assert path.turnover_fraction.notna().all()
        assert indexed.loc[event_id, "cum_turnover_since_zone"] == pytest.approx(path.turnover_fraction.sum())
    assert "float_share" not in daily.columns and "volume" not in daily.columns
    assert features.turnover_available.all()


def test_feature_freeze_is_outcome_blind_and_terciles_are_exact(features: pd.DataFrame) -> None:
    freeze = json.loads(discovery.FEATURE_FREEZE.read_text(encoding="utf-8"))
    assert freeze["status"] == "FROZEN_BEFORE_OUTCOME_ATTACHMENT"
    assert freeze["outcome_columns_present"] == []
    assert discovery.v1.sha256_file(discovery.FEATURES) == freeze["feature_panel_sha256"]
    assert not set(discovery.OUTCOMES).intersection(features.columns)
    for column in discovery.TERCILE_FEATURES:
        bounds = freeze["tercile_boundaries"][column]
        assert bounds["low_high_boundary"] < bounds["mid_high_boundary"]
        assert features[f"{column}_bin"].notna().sum() == features[column].notna().sum()


def test_clean_resolution_and_u_before_loss_labels_match_frozen_anatomy(features: pd.DataFrame) -> None:
    anatomy = pd.read_parquet(discovery.anatomy.EVENTS).set_index("event_id").loc[features.event_id]
    clean20 = anatomy.legal_full_fill_20d & anatomy.u_before_loss10_20d
    clean40 = anatomy.legal_full_fill_40d & anatomy.u_before_loss10_40d
    assert clean20.mean() == pytest.approx(0.6672862453531598)
    assert clean40.mean() == pytest.approx(0.6765799256505576)
    assert anatomy.u_before_loss5_60d.mean() == pytest.approx(0.47769516728624534)
    assert anatomy.u_before_loss10_60d.mean() == pytest.approx(0.6784386617100372)
    assert anatomy.u_before_loss20_60d.mean() == pytest.approx(0.828996282527881)


def test_d60_boundary_qd010_and_sealed_periods(features: pd.DataFrame, result: dict[str, object]) -> None:
    source = pd.read_parquet(discovery.outcome.SOURCE_EVENTS)
    acceptance = pd.read_parquet(discovery.outcome.ACCEPTANCE)
    entries = pd.read_parquet(discovery.outcome.ENTRIES)
    merged = source.merge(acceptance[["event_id"]], on="event_id", how="left").merge(entries, on="event_id", how="left")
    executable = merged.entry_time.notna() & ~merged.entry_coord_price.gt(merged.U).fillna(False)
    assert executable.sum() == 598
    risk = pd.read_parquet(discovery.strategy.TRADE_CANDIDATES)
    blocked = set(risk.loc[risk.entry_family.eq("E1_FIRST_ACCEPT") & risk.risk_blocked_entry, "event_id"])
    assert len(blocked) == 4 and blocked.isdisjoint(set(features.event_id))
    calendar = pd.read_parquet(discovery.v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    last = int(calendar.loc[pd.to_datetime(calendar.trade_date).le(pd.Timestamp("2021-12-31")), "cal_idx"].max())
    assert features.entry_cal_idx.astype(int).add(60).le(last).all()
    assert result["source_reconciliation"]["complete_common_60d"] == 538
    assert result["audit"]["post_2021_outcome_read_count"] == 0
    assert result["validation_opened"] is False
    assert result["repository_2024_plus_data_opened"] is False


def test_date_equal_aggregation_and_all_audits(result: dict[str, object]) -> None:
    fixture = pd.DataFrame({"reentry_date": pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03"]), "clean_resolve_20": [0, 1, 1]})
    for column in discovery.OUTCOMES:
        if column not in fixture:
            fixture[column] = fixture.clean_resolve_20
    summary = discovery.date_equal_metrics(fixture, "reentry_date")
    assert summary["clean_resolve_20"] == pytest.approx(0.75)
    assert all(value == 0 for value in result["audit"].values())
    assert result["verdict"] == "ENTRY_QUALITY_PRIMARILY_FRESHNESS_DRIVEN"
