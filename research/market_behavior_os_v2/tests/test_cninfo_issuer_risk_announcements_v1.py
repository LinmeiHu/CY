from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    fetch_cninfo_issuer_risk_announcements_v1 as subject,
)


def test_midnight_source_timestamp_becomes_next_day_available() -> None:
    raw_ms = int(pd.Timestamp("2021-12-31 00:00:00", tz="Asia/Shanghai").tz_convert("UTC").timestamp() * 1000)

    announcement_at, available_at, precision = subject.causal_times(raw_ms)

    assert announcement_at == pd.Timestamp("2021-12-31 00:00:00")
    assert available_at == pd.Timestamp("2022-01-01 00:00:00")
    assert precision == "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"


def test_intraday_source_timestamp_keeps_exact_availability() -> None:
    raw_ms = int(pd.Timestamp("2026-05-29 19:40:09", tz="Asia/Shanghai").tz_convert("UTC").timestamp() * 1000)

    announcement_at, available_at, precision = subject.causal_times(raw_ms)

    assert announcement_at == pd.Timestamp("2026-05-29 19:40:09")
    assert available_at == announcement_at
    assert precision == "SOURCE_SECOND"


def test_normalize_title_removes_highlight_markup() -> None:
    assert subject.normalize_title("涉及<em>违规</em><em>担保</em>的公告") == "涉及违规担保的公告"


def test_page_count_uses_ceiling_instead_of_source_floor() -> None:
    assert subject.expected_pages(2302) == 77
