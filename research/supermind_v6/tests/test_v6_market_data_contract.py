from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from build_v6_market_data import normalize_daily  # noqa: E402
from v6_data_common import (  # noqa: E402
    canonical_symbol,
    exchange_for,
    parse_strategy_pool,
    strategy_sha256,
    universe_sha256,
)


def _provider_frame(prefix: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [date(2020, 1, 2), date(2020, 1, 3)],
            f"{prefix}_open": [1.0, 1.1],
            f"{prefix}_close": [1.1, 1.2],
            f"{prefix}_high": [1.2, 1.3],
            f"{prefix}_low": [0.9, 1.0],
            f"{prefix}_volume": [1000.0, 2000.0],
            f"{prefix}_amount": [105000.0, 230000.0],
            f"{prefix}_amplitude_pct": [1.0, 1.0],
            f"{prefix}_change_pct": [1.0, 1.0],
            f"{prefix}_change": [0.1, 0.1],
            f"{prefix}_turnover_rate_pct": [2.0, 3.0],
        }
    )


def test_frozen_pool_is_parsed_without_manual_copy() -> None:
    pool = parse_strategy_pool()
    assert len(pool) == 152
    assert len(set(pool)) == 152
    assert pool[0] == "510300"
    assert (
        universe_sha256(pool) == "0a647dba2e5ef80088c9ec9c9ebdb889b1744ddb1686d0e20867a9a7059f98c3"
    )
    assert strategy_sha256() == "7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33"


def test_exchange_mapping_is_explicit() -> None:
    assert exchange_for("510300") == "SH"
    assert canonical_symbol("510300") == "510300.SH"
    assert exchange_for("159915") == "SZ"
    assert canonical_symbol("159915") == "159915.SZ"


def test_normalizer_preserves_amount_and_native_volume_without_fill() -> None:
    raw = _provider_frame("raw")
    qfq = _provider_frame("qfq")
    qfq["qfq_close"] = [0.55, 0.60]
    qfq["qfq_open"] = [0.50, 0.55]
    qfq["qfq_high"] = [0.60, 0.65]
    qfq["qfq_low"] = [0.45, 0.50]
    normalized = normalize_daily(
        "510300",
        raw,
        qfq,
        list_date=date(2020, 1, 3),
        snapshot_id="test",
        raw_sha256="a" * 64,
        qfq_sha256="b" * 64,
    )
    assert len(normalized) == len(raw)
    assert normalized.loc[0, "row_status"] == "NOT_LISTED"
    assert normalized.loc[1, "row_status"] == "VALID"
    assert normalized.loc[1, "volume_raw"] == 2000.0
    assert normalized.loc[1, "volume_shares"] == 200000.0
    assert normalized.loc[1, "amount_cny"] == 230000.0
    assert normalized.loc[1, "raw_turnover_rate_pct"] == 3.0
    assert normalized.loc[1, "adj_factor_close_ratio"] == 0.5
