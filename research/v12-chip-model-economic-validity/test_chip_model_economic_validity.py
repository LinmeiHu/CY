from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cyq_game.chip.checkpoint_compact_codec import decode_compact_checkpoint

STUDY_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "chip_model_economic_validity",
    STUDY_DIR / "run_chip_model_economic_validity.py",
)
assert SPEC is not None and SPEC.loader is not None
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)
PROTOCOL = json.loads((STUDY_DIR / "preregistered_protocol.json").read_text())


def _record(day: str, close: float, *, action: bool = False) -> dict[str, object]:
    return {
        "trade_date": pd.Timestamp(day),
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 100.0,
        "turnover_fraction": 0.01,
        "tradable": True,
        "valid_index": 0,
        "corporate_action_count": int(action),
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "cash_per_share": 0.0,
        "share_multiplier": 2.0 if action else 1.0,
    }


def test_distribution_descriptors_conserve_known_mass() -> None:
    distribution = STUDY.Distribution(
        coordinates=np.asarray([8.0, 10.0, 12.0]),
        shares=np.asarray([20.0, 50.0, 20.0]),
        free_float=100.0,
        known_fraction=0.9,
    )
    result = STUDY.distribution_descriptors(distribution, 10.0)
    assert result["weighted_median"] == 10.0
    assert result["known_cost_fraction"] == 0.9
    assert math.isclose(result["mass_below_price"], 0.2)
    assert math.isclose(result["mass_above_price"], 0.2)
    assert math.isclose(STUDY.mass_in_band(distribution, 9.0, 11.0), 0.5)


def test_frozen_mass_requires_the_exact_declared_residual() -> None:
    shares = np.asarray([0.1, 0.2], dtype=np.float64)
    free_float = 0.3
    residual = math.fsum(shares.tolist()) - free_float
    STUDY.validate_frozen_mass(shares, free_float, STUDY.f64be_bits(residual))
    with pytest.raises(RuntimeError, match="exact bits"):
        STUDY.validate_frozen_mass(shares, free_float, STUDY.f64be_bits(0.0))


def test_placebo_is_low_mass_and_does_not_overlap_peak() -> None:
    distribution = STUDY.Distribution(
        coordinates=np.asarray([80.0, 90.0, 100.0]),
        shares=np.asarray([1.0, 40.0, 59.0]),
        free_float=100.0,
        known_fraction=1.0,
    )
    result = STUDY.choose_placebo(
        side="SUPPORT",
        close=100.0,
        lower=88.0,
        center=90.0,
        upper=92.0,
        real_mass=0.4,
        all_bands=[(88.0, 92.0)],
        distributions=[distribution],
        protocol=PROTOCOL,
    )
    assert result is not None
    assert result["placebo_upper"] < 88.0 or result["placebo_lower"] > 92.0
    assert result["placebo_mass"] <= 0.2


def test_touch_starts_after_definition_and_measures_future_only() -> None:
    dates = pd.bdate_range("2020-01-02", periods=50)
    closes = [100.0, 96.0, 91.0, 92.0, 94.0, *([95.0] * 45)]
    records = []
    for index, (day, close) in enumerate(zip(dates, closes, strict=True)):
        item = _record(str(day.date()), close)
        item["valid_index"] = index
        records.append(item)
    status, touches = STUDY.simulate_level(
        symbol="000001.SZ",
        checkpoint_date=dates[0],
        side="SUPPORT",
        lower=89.0,
        center=90.0,
        upper=92.0,
        records=records,
        date_index={item["trade_date"]: index for index, item in enumerate(records)},
        protocol=PROTOCOL,
    )
    assert status["path_valid"] is True
    assert status["touched"] is True
    assert touches[0]["touch_date"] > dates[0]
    assert touches[0]["future_return_1"] == 92.0 / 91.0 - 1.0
    assert touches[0]["reaction_probability"] is True


def test_corporate_action_rebases_frozen_level_and_prior_close() -> None:
    dates = pd.bdate_range("2020-01-02", periods=45)
    closes = [100.0, 50.0, 46.0, 47.0, *([48.0] * 41)]
    records = []
    for index, (day, close) in enumerate(zip(dates, closes, strict=True)):
        item = _record(str(day.date()), close, action=index == 1)
        item["valid_index"] = index
        records.append(item)
    status, touches = STUDY.simulate_level(
        symbol="000001.SZ",
        checkpoint_date=dates[0],
        side="SUPPORT",
        lower=44.0 * 2,
        center=45.0 * 2,
        upper=46.0 * 2,
        records=records,
        date_index={item["trade_date"]: index for index, item in enumerate(records)},
        protocol=PROTOCOL,
    )
    assert status["path_valid"] is True
    assert touches[0]["touch_band_center"] == 45.0
    assert touches[0]["touch_date"] == dates[2]


def test_cluster_interval_reports_effective_event_count() -> None:
    frame = pd.DataFrame(
        {
            "metric": [0.0, 1.0, 1.0, 1.0],
            "cluster": ["a", "a", "b", "c"],
        }
    )
    result = STUDY.cluster_ci(frame, "metric", "cluster", seed=7, replicates=50)
    assert result["N"] == 4
    assert result["independent_event_count"] == 3
    assert math.isclose(result["effect"], (0.5 + 1.0 + 1.0) / 3.0)


def test_protocol_freezes_requested_versions_and_horizons() -> None:
    assert PROTOCOL["frozen_inputs"]["frozen_root_manifest_sha256"] == STUDY.EXPECTED_ROOT_SHA256
    assert PROTOCOL["frozen_inputs"]["freeze_lock_sha256"] == STUDY.EXPECTED_LOCK_SHA256
    assert tuple(PROTOCOL["chronology"]["future_horizons_sessions"]) == STUDY.HORIZONS
    assert PROTOCOL["chronology"]["t_plus_one"] is True


def test_vectorized_reader_matches_authoritative_checkpoint_decoder() -> None:
    path = Path(
        "/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828/"
        "symbol=000001.SZ/checkpoints/month-06-2020-06-30.npz"
    )
    fast = STUDY.fast_decode_checkpoint(path)
    authoritative = decode_compact_checkpoint(path)
    assert fast.symbol == authoritative.symbol
    assert fast.checkpoint_date == authoritative.checkpoint_date
    for fast_state, state in zip(fast.model_states, authoritative.model_states, strict=True):
        expected = STUDY.distribution_from_checkpoint(authoritative, state)
        actual = STUDY.distribution_from_checkpoint(fast, fast_state)
        assert fast_state.seller_model == state.seller_model
        assert actual.free_float == expected.free_float
        assert np.array_equal(np.sort(actual.coordinates), np.sort(expected.coordinates))
        assert actual.shares.sum() == expected.shares.sum()
    for fast_scope, scope in zip(
        fast.temporal_tracker.scopes,
        authoritative.temporal_tracker.scopes,
        strict=True,
    ):
        assert fast_scope.scope == scope.scope
        assert fast_scope.base_track_id == scope.base_track_id
        assert [STUDY._peak_values(item) for item in fast_scope.previous_peaks] == [
            STUDY._peak_values(item) for item in scope.previous_peaks
        ]
