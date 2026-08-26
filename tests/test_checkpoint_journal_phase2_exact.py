from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_journal_writer import (
    PHASE2_SYMBOLS,
    arrow_exact_mismatch_count,
    checkpoint_dates,
)


def test_phase2_sample_and_month_end_cadence_are_frozen() -> None:
    assert PHASE2_SYMBOLS == ("002260.SZ", "002706.SZ", "300604.SZ")
    dates = (
        __import__("datetime").date(2020, 1, 2),
        __import__("datetime").date(2020, 1, 23),
        __import__("datetime").date(2020, 2, 3),
        __import__("datetime").date(2020, 2, 28),
    )
    assert checkpoint_dates(dates) == (dates[0], dates[1], dates[3])


def test_exact_oracle_comparison_distinguishes_ieee754_signed_zero(tmp_path: Path) -> None:
    positive = tmp_path / "positive.parquet"
    negative = tmp_path / "negative.parquet"
    pq.write_table(pa.table({"shares": [0.0], "nested": [[0.0]]}), positive)
    pq.write_table(pa.table({"shares": [-0.0], "nested": [[-0.0]]}), negative)
    assert arrow_exact_mismatch_count(positive, positive) == 0
    assert arrow_exact_mismatch_count(positive, negative) > 0
