from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pit_universe import (  # noqa: E402
    is_date_effective_member,
    listed_session_age,
    listing_age_eligible,
)


def test_future_listing_never_appears_before_effective_date() -> None:
    assert not is_date_effective_member(date(2024, 12, 31), date(2025, 1, 2), None)
    assert is_date_effective_member(date(2025, 1, 2), date(2025, 1, 2), None)


def test_delisted_security_keeps_history_through_out_date() -> None:
    listed = date(2020, 1, 2)
    out = date(2024, 6, 28)
    assert is_date_effective_member(date(2024, 6, 27), listed, out)
    assert is_date_effective_member(out, listed, out)
    assert not is_date_effective_member(date(2024, 7, 1), listed, out)


def test_listing_age_179_fails_and_exactly_180_passes() -> None:
    start = date(2024, 1, 2)
    sessions = [start + timedelta(days=index) for index in range(200)]
    assert listed_session_age(sessions[178], start, sessions) == 179
    assert listed_session_age(sessions[179], start, sessions) == 180
    assert not listing_age_eligible(179)
    assert listing_age_eligible(180)


def test_pit_builder_cannot_read_current_survivor_manifest() -> None:
    source = (SCRIPTS / "build_chinext_v1_pit_master.py").read_text(encoding="utf-8")
    assert "chinext_current_survivor_universe.json" not in source
