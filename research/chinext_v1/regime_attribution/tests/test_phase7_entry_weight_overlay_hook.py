from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts/run_chinext_v1_smoke.py"
)
sys.path.insert(0, str(SCRIPT.parent))
import run_chinext_v1_smoke as smoke  # noqa: E402


def test_all_one_overlay_matches_frozen_target_weights() -> None:
    config = smoke.ChinNextV1Config()
    previous = ("300001.SZ", "300002.SZ")
    desired = ("300001.SZ", "300002.SZ", "300003.SZ")
    old = {symbol: config.target_weight for symbol in previous}
    result = smoke.entry_regime_target_weights(
        desired=desired,
        previous=previous,
        previous_weights=old,
        new_entry_multiplier=1.0,
        config=config,
    )
    assert result == smoke.desired_target_weights(desired, config)


def test_half_size_applies_only_to_new_member_and_remains_sticky() -> None:
    config = smoke.ChinNextV1Config()
    first = smoke.entry_regime_target_weights(
        desired=("A", "B"),
        previous=("A",),
        previous_weights={"A": 0.05},
        new_entry_multiplier=0.5,
        config=config,
    )
    assert first == {"A": 0.05, "B": 0.05}
    second = smoke.entry_regime_target_weights(
        desired=("A", "B", "C"),
        previous=("A", "B"),
        previous_weights=first,
        new_entry_multiplier=1.0,
        config=config,
    )
    assert second == {"A": 0.05, "B": 0.05, "C": 0.10}


def test_zero_size_reserves_member_without_creating_pending_buy() -> None:
    config = smoke.ChinNextV1Config()
    pending: dict[str, object] = {}
    smoke.schedule_target_set(
        desired=("A",),
        previous=(),
        positions={},
        pending=pending,
        signal_date=date(2024, 1, 2),
        reason="REGIME_TEST",
        config=config,
        target_weights={"A": 0.0},
    )
    assert pending == {}


def test_explicit_weights_fail_closed_on_member_or_bound_mismatch() -> None:
    config = smoke.ChinNextV1Config()
    with pytest.raises(ValueError, match="exactly match"):
        smoke.schedule_target_set(
            desired=("A",), previous=(), positions={}, pending={},
            signal_date=date(2024, 1, 2), reason="TEST", config=config,
            target_weights={},
        )
    with pytest.raises(ValueError, match="outside"):
        smoke.schedule_target_set(
            desired=("A",), previous=(), positions={}, pending={},
            signal_date=date(2024, 1, 2), reason="TEST", config=config,
            target_weights={"A": 0.11},
        )
