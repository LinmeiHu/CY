from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/vectorized_market_minute_adapter.py"
MODULE_SPEC = importlib.util.spec_from_file_location("vectorized_market_minute_adapter", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
minute = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(minute)


def _synthetic_table(*, missing_position: int | None = None, adjust: str = "none") -> pa.Table:
    times = np.array(
        [np.datetime64("2020-02-03") + np.timedelta64(int(value), "m") for value in minute.EXPECTED_MINUTES],
        dtype="datetime64[ns]",
    )
    base = np.linspace(10.0, 10.5, 241)
    close = base.copy()
    open_ = np.r_[base[0], base[:-1]]
    high = np.maximum(open_, close) + 0.01
    low = np.minimum(open_, close) - 0.01
    keep = np.ones(241, dtype=bool)
    if missing_position is not None:
        keep[missing_position] = False
    count = int(keep.sum())
    return pa.table(
        {
            "symbol": ["000001"] * count,
            "exchange": ["SZ"] * count,
            "period": ["1m"] * count,
            "adjust": [adjust] * count,
            "trade_date": pa.array([date(2020, 2, 3)] * count, type=pa.date32()),
            "bar_end_time": pa.array(times[keep], type=pa.timestamp("ns")),
            "open": open_[keep],
            "high": high[keep],
            "low": low[keep],
            "close": close[keep],
            "volume": np.full(count, 100.0),
            "amount": close[keep] * 100.0,
            "source": ["SYNTHETIC"] * count,
        }
    )


def test_expected_grid_preserves_auction_and_lunch() -> None:
    assert len(minute.EXPECTED_MINUTES) == 241
    assert minute.EXPECTED_MINUTES[0] == 9 * 60 + 30
    assert minute.EXPECTED_MINUTES[120] == 11 * 60 + 30
    assert minute.EXPECTED_MINUTES[121] == 13 * 60 + 1
    assert minute.EXPECTED_MINUTES[-1] == 15 * 60


def test_vectorized_descriptor_is_finite_and_deterministic() -> None:
    table = _synthetic_table()
    first, opening_first, audit = minute.vectorized_session_descriptors(table)
    second, opening_second, _ = minute.vectorized_session_descriptors(table)
    assert len(first) == 1
    assert np.isfinite(first[list(minute.DESCRIPTOR_COLUMNS)].to_numpy(float)).all()
    assert audit["descriptor_sessions"] == 1
    assert audit["maximum_five_minute_volume_conservation_difference"] == 0.0
    assert audit["maximum_five_minute_amount_conservation_difference"] == 0.0
    assert first.equals(second)
    assert opening_first.equals(opening_second)


def test_missing_minute_fails_closed() -> None:
    descriptors, opening, audit = minute.vectorized_session_descriptors(
        _synthetic_table(missing_position=121)
    )
    assert descriptors.empty
    assert opening.empty
    assert audit["invalid_grid_sessions"] == 1


def test_adjusted_row_is_rejected() -> None:
    try:
        minute.vectorized_session_descriptors(_synthetic_table(adjust="qfq"))
    except minute.VectorMinuteAdapterError as exc:
        assert "adjusted" in str(exc)
    else:
        raise AssertionError("adjusted raw data was accepted")
