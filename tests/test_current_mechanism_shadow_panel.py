from __future__ import annotations

import runpy
from datetime import date, datetime
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1] / "scripts/build_current_mechanism_shadow_panel.py"
)
MODULE = runpy.run_path(str(SCRIPT))


def _row(day: date, session: int) -> dict[str, object]:
    return {
        "symbol": "000001.SZ",
        "trade_date": day,
        "decision_at": datetime.combine(day, datetime.min.time()).replace(hour=15),
        "daily_snapshot_id": f"daily:{day}",
        "symbol_session_index": session,
    }


def test_current_candidate_selector_keeps_frozen_cooldown_and_week_rule() -> None:
    selected = MODULE["_select_candidates"](
        [
            _row(date(2026, 1, 5), 100),
            _row(date(2026, 1, 6), 101),
            _row(date(2026, 2, 2), 120),
        ]
    )

    assert [row["trade_date"] for row in selected] == [
        date(2026, 1, 5),
        date(2026, 2, 2),
    ]
    assert all(row["candidate_uses_chip_fields"] is False for row in selected)


def test_current_candidate_query_only_changes_registered_date_anchors() -> None:
    query = MODULE["_candidate_query"](
        (Path("year=2025.parquet"), Path("year=2026.parquet"))
    )

    assert "2025-01-01" in query
    assert "2026-08-24" in query
    assert "2022-12-30" not in query
