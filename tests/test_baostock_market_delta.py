from __future__ import annotations

import runpy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

MODULE = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "fetch_baostock_market_delta.py")
)
_is_a_share_code = MODULE["_is_a_share_code"]
_validate_decision_cutoff = MODULE["_validate_decision_cutoff"]
_existing_parent = MODULE["_existing_parent"]
_resume_reference_data = MODULE["_resume_reference_data"]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("sh.600000", True),
        ("sh.688001", True),
        ("sz.000001", True),
        ("sz.300750", True),
        ("bj.920001", False),
        ("sh.900901", False),
        ("sz.200001", False),
        ("sh.000001", False),
    ],
)
def test_is_a_share_code(code: str, expected: bool) -> None:
    assert _is_a_share_code(code) is expected


def test_decision_cutoff_blocks_unfinished_same_day() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    with pytest.raises(ValueError, match="before 15:00"):
        _validate_decision_cutoff(
            date(2026, 8, 25), datetime(2026, 8, 25, 14, 59, tzinfo=timezone)
        )
    _validate_decision_cutoff(
        date(2026, 8, 25), datetime(2026, 8, 25, 15, 0, tzinfo=timezone)
    )


def test_existing_parent_walks_up_from_missing_path(tmp_path: Path) -> None:
    assert _existing_parent(tmp_path / "missing" / "child") == tmp_path.resolve()


def test_resume_reference_data_requires_complete_reference_set(tmp_path: Path) -> None:
    assert _resume_reference_data(
        tmp_path, date(2026, 8, 13), date(2026, 8, 24)
    ) is None
