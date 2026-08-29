from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    import xtquant  # type: ignore[import-not-found]  # noqa: F401
except ModuleNotFoundError:
    sys.modules["xtquant"] = types.SimpleNamespace(xtdata=types.SimpleNamespace())

from export_v6_from_qmt import normalize_critical, normalize_daily  # noqa: E402


def _qmt_frame(index: list[str], price_scale: float = 1.0) -> pd.DataFrame:
    count = len(index)
    return pd.DataFrame(
        {
            "time": list(range(count)),
            "open": [1.0 * price_scale] * count,
            "high": [1.2 * price_scale] * count,
            "low": [0.9 * price_scale] * count,
            "close": [1.1 * price_scale] * count,
            "volume": [1_000.0] * count,
            "amount": [105_000.0] * count,
            "preClose": [1.0 * price_scale] * count,
            "suspendFlag": [0] * count,
        },
        index=index,
    )


def test_qmt_daily_keeps_raw_and_front_prices_without_inserting_dates() -> None:
    index = ["20200102", "20200103"]
    frame = normalize_daily(
        "510300.SH",
        _qmt_frame(index),
        _qmt_frame(index, price_scale=0.5),
    )
    assert len(frame) == 2
    assert frame["qmt_index"].tolist() == index
    assert frame["row_status"].tolist() == ["VALID", "VALID"]
    assert frame["raw_close"].tolist() == [1.1, 1.1]
    assert frame["pre_adj_close"].tolist() == [0.55, 0.55]
    assert frame["adj_factor_close_ratio"].tolist() == [0.5, 0.5]
    assert frame["volume_raw"].tolist() == [1_000.0, 1_000.0]
    assert frame["volume_shares"].tolist() == [100_000.0, 100_000.0]
    assert frame["amount_cny"].tolist() == [105_000.0, 105_000.0]


def test_qmt_critical_export_uses_exact_bar_keys_and_1457_open() -> None:
    index = [
        "20200102093000",
        "20200102100000",
        "20200102145700",
        "20200102150000",
    ]
    raw = _qmt_frame(index)
    raw.loc["20200102145700", "open"] = 1.07
    raw.loc["20200102145700", "close"] = 1.09
    frame = normalize_critical("510300.SH", raw, _qmt_frame(index, price_scale=0.5))
    assert frame["qmt_index"].tolist() == [
        "20200102093000",
        "20200102145700",
        "20200102150000",
    ]
    assert frame["bar_role"].tolist() == [
        "OPEN_BAR_09_30",
        "PSEUDO_CLOSE_14_57_OPEN",
        "FINAL_CLOSE_BAR",
    ]
    row_1457 = frame[frame["bar_role"] == "PSEUDO_CLOSE_14_57_OPEN"].iloc[0]
    assert row_1457["raw_open"] == 1.07
    assert row_1457["raw_close"] == 1.09
    assert row_1457["timezone"] == "Asia/Shanghai"
    assert row_1457["opening_auction_status"].endswith("not_proven_exact_opening_auction")
