from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_v6_open_execution_availability import build_symbol_availability  # noqa: E402


def test_missing_open_is_no_fill_without_synthetic_price() -> None:
    daily = pd.DataFrame(
        {
            "trade_date": [date(2025, 8, 27), date(2025, 8, 28), date(2025, 8, 29)],
            "row_status": ["VALID", "VALID", "VALID"],
        }
    )
    minute = pd.DataFrame(
        {
            "trade_date": [
                date(2025, 8, 27),
                date(2025, 8, 27),
                date(2025, 8, 28),
                date(2025, 8, 28),
                date(2025, 8, 28),
                date(2025, 8, 29),
                date(2025, 8, 29),
            ],
            "bar_role": [
                "PSEUDO_CLOSE_14_57_OPEN",
                "FINAL_CLOSE_BAR",
                "OPEN_BAR_09_30",
                "PSEUDO_CLOSE_14_57_OPEN",
                "FINAL_CLOSE_BAR",
                "PSEUDO_CLOSE_14_57_OPEN",
                "FINAL_CLOSE_BAR",
            ],
            "raw_open": [1.0, 1.0, 1.1, 1.1, 1.1, 1.2, 1.2],
            "pre_adj_open": [0.5, 0.5, 0.55, 0.55, 0.55, 0.6, 0.6],
            "raw_close": [1.0, 1.0, 1.1, 1.1, 1.1, 1.2, 1.2],
            "pre_adj_close": [0.5, 0.5, 0.55, 0.55, 0.55, 0.6, 0.6],
            "row_status": ["VALID"] * 7,
            "datetime": [f"2025-08-{27 + i // 3:02d}T09:30:00+08:00" for i in range(7)],
            "available_at": [f"2025-08-{27 + i // 3:02d}T09:30:00+08:00" for i in range(7)],
            "snapshot_id": ["test"] * 7,
        }
    )
    result = build_symbol_availability(
        "510300.SH",
        daily,
        minute,
        evaluation_start=date(2025, 8, 28),
        partition_sha256="a" * 64,
    )

    assert result["trade_date"].tolist() == [date(2025, 8, 28), date(2025, 8, 29)]
    assert result["execution_status"].tolist() == [
        "OBSERVED_VALID_09_30_BAR",
        "MISSING_09_30_BAR",
    ]
    missing = result.iloc[1]
    assert missing["primary_execution_policy"] == "NO_FILL_RETRY_NEXT_SESSION"
    assert missing["sensitivity_execution_policy"].endswith("DIAGNOSTIC_ONLY")
    assert pd.isna(missing["raw_open"])
    assert pd.isna(missing["pre_adj_open"])
    assert not bool(missing["synthetic_price_used"])
    assert bool(missing["tail_signal_available_14_57"])
    assert bool(missing["executable_15_00"])


def test_observed_zero_volume_open_is_fail_closed() -> None:
    daily = pd.DataFrame(
        {"trade_date": [date(2025, 8, 28)], "row_status": ["VALID"]}
    )
    minute = pd.DataFrame(
        {
            "trade_date": [date(2025, 8, 28)],
            "bar_role": ["OPEN_BAR_09_30"],
            "raw_open": [1.0],
            "pre_adj_open": [0.5],
            "raw_close": [1.0],
            "pre_adj_close": [0.5],
            "row_status": ["NONPOSITIVE_VOLUME"],
            "datetime": ["2025-08-28T09:30:00+08:00"],
            "available_at": ["2025-08-28T09:30:00+08:00"],
            "snapshot_id": ["test"],
        }
    )
    result = build_symbol_availability(
        "510300.SH",
        daily,
        minute,
        evaluation_start=date(2025, 8, 28),
        partition_sha256="c" * 64,
    )
    row = result.iloc[0]
    assert bool(row["observed_09_30"])
    assert not bool(row["executable_09_30"])
    assert row["execution_status"] == "OBSERVED_INVALID_09_30_BAR"
    assert row["primary_execution_policy"] == "NO_FILL_RETRY_NEXT_SESSION"
    assert pd.isna(row["raw_open"])
    assert pd.isna(row["pre_adj_open"])


def test_nonvalid_daily_session_is_not_marked_missing_open() -> None:
    daily = pd.DataFrame(
        {
            "trade_date": [date(2025, 8, 28), date(2025, 8, 29)],
            "row_status": ["VALID", "SUSPENDED"],
        }
    )
    minute = pd.DataFrame(
        {
            "trade_date": [date(2025, 8, 28)],
            "bar_role": ["OPEN_BAR_09_30"],
            "raw_open": [1.0],
            "pre_adj_open": [0.5],
            "raw_close": [1.0],
            "pre_adj_close": [0.5],
            "row_status": ["VALID"],
            "datetime": ["2025-08-28T09:30:00+08:00"],
            "available_at": ["2025-08-28T09:30:00+08:00"],
            "snapshot_id": ["test"],
        }
    )
    result = build_symbol_availability(
        "510300.SH",
        daily,
        minute,
        evaluation_start=date(2025, 8, 28),
        partition_sha256="b" * 64,
    )
    assert result["trade_date"].tolist() == [date(2025, 8, 28)]
    assert result["observed_09_30"].tolist() == [True]


def test_invalid_tail_signal_and_close_are_fail_closed() -> None:
    daily = pd.DataFrame(
        {"trade_date": [date(2025, 8, 28)], "row_status": ["VALID"]}
    )
    minute = pd.DataFrame(
        {
            "trade_date": [date(2025, 8, 28)] * 3,
            "bar_role": [
                "OPEN_BAR_09_30",
                "PSEUDO_CLOSE_14_57_OPEN",
                "FINAL_CLOSE_BAR",
            ],
            "raw_open": [1.0, 1.1, 1.2],
            "pre_adj_open": [0.5, 0.55, 0.6],
            "raw_close": [1.0, 1.1, 1.2],
            "pre_adj_close": [0.5, 0.55, 0.6],
            "row_status": ["VALID", "NONPOSITIVE_VOLUME", "NONPOSITIVE_VOLUME"],
            "datetime": [
                "2025-08-28T09:30:00+08:00",
                "2025-08-28T14:57:00+08:00",
                "2025-08-28T15:00:00+08:00",
            ],
            "available_at": [
                "2025-08-28T09:30:00+08:00",
                "2025-08-28T14:57:00+08:00",
                "2025-08-28T15:00:00+08:00",
            ],
            "snapshot_id": ["test"] * 3,
        }
    )
    result = build_symbol_availability(
        "510300.SH",
        daily,
        minute,
        evaluation_start=date(2025, 8, 28),
        partition_sha256="d" * 64,
    )
    row = result.iloc[0]
    assert not bool(row["tail_signal_available_14_57"])
    assert row["tail_signal_policy"].startswith("NO_INTRADAY_TAIL_SIGNAL")
    assert pd.isna(row["signal_raw_price"])
    assert not bool(row["executable_15_00"])
    assert row["close_execution_policy"] == "NO_FILL_RETRY_NEXT_SESSION"
    assert pd.isna(row["close_raw_price"])
