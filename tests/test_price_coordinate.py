from __future__ import annotations

from datetime import date

import pytest

from cyq_game.chip.peaks import CanonicalPeak, TemporalPeakTracker
from cyq_game.chip.price_coordinate import (
    PRICE_COORDINATE_VERSION,
    canonical_action_component_id,
    rebase_economic_price,
)


def _peak(center: float) -> CanonicalPeak:
    return CanonicalPeak(
        center_bucket=100,
        center_price=center,
        lower_bucket=99,
        lower_price=center - 0.5,
        upper_bucket=101,
        upper_price=center + 0.5,
        mass=0.8,
        prominence=0.2,
        width_pct=1.0 / (center - 0.5),
        age_mean=None,
        formation_date="2026-08-24",
    )


def test_action_identity_commits_source_provenance_and_is_idempotent() -> None:
    arguments = {
        "symbol": "000001.SZ",
        "effective_date": date(2026, 8, 25),
        "kind": "CASH_DIVIDEND",
        "source_action_ids": ("CNINFO-2", "CNINFO-1"),
        "snapshot_id": "snapshot-1",
        "cash_per_share": 0.1,
    }
    first = canonical_action_component_id(**arguments)
    second = canonical_action_component_id(
        **{**arguments, "source_action_ids": ("CNINFO-1", "CNINFO-2")}
    )
    assert first == second
    assert first != canonical_action_component_id(
        **{**arguments, "cash_per_share": 0.2}
    )
    assert PRICE_COORDINATE_VERSION == "causal-economic-price-v2"


def test_peak_tracker_rebases_prior_identity_once_on_action_date() -> None:
    tracker = TemporalPeakTracker(symbol="000001.SZ", model="uniform")
    before = tracker.update(as_of=date(2026, 8, 24), candidates=(_peak(10.0),))
    assert before.tracked_base_peak is not None
    track_id = before.tracked_base_peak.peak_track_id

    tracker.apply_corporate_action(
        action_id="action-1", cash_per_share=0.2, share_multiplier=2.0
    )
    tracker.apply_corporate_action(
        action_id="action-1", cash_per_share=0.2, share_multiplier=2.0
    )
    after = tracker.update(
        as_of=date(2026, 8, 25),
        candidates=(_peak(rebase_economic_price(10.0, cash_per_share=0.2, share_multiplier=2.0)),),
    )
    assert after.tracked_base_peak is not None
    assert after.tracked_base_peak.peak_track_id == track_id
    assert after.tracked_base_peak.age == 2


def test_coordinate_rejects_nonfinite_then_nonpositive_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        rebase_economic_price(float("nan"))
    with pytest.raises(ValueError, match="positive"):
        rebase_economic_price(1.0, cash_per_share=1.0)
