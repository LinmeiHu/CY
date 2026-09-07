from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from five_strategy_bundle.io import write_parquet
from five_strategy_bundle.strategies.atrdr import build_market_state
from five_strategy_bundle.strategies.atrdr_post import apply_capacity


def test_market_state_uses_frozen_universe_and_exact_calendar_lags(tmp_path: Path) -> None:
    dates = pd.bdate_range("2024-01-01", periods=61)
    rows = []
    for symbol, industry, scale in (
        ("000001.SZ", "银行", 1.0),
        ("600001.SH", "煤炭开采", 100.0),
    ):
        for index, date in enumerate(dates):
            rows.append({
                "symbol": symbol, "sleeve": "MAIN", "causal_industry": industry,
                "trade_date": date, "cal_idx": index, "coord_close": scale * (100 + index),
                "current_valid": True, "hard_valid": index != 60, "is_st": False,
                "available_at": date + pd.Timedelta(hours=15),
                "decision_at": date + pd.Timedelta(hours=15),
            })
    # A missing market session makes both positional lag endpoints non-exact.
    for index, date in enumerate(dates):
        if index == 40:
            continue
        rows.append({
            "symbol": "300001.SZ", "sleeve": "CHINEXT", "causal_industry": "软件开发",
            "trade_date": date, "cal_idx": index, "coord_close": 50 + index,
            "current_valid": True, "hard_valid": True, "is_st": False,
            "available_at": date + pd.Timedelta(hours=15),
            "decision_at": date + pd.Timedelta(hours=15),
        })
    source = tmp_path / "daily.parquet"
    write_parquet(pd.DataFrame(rows), source)
    result = build_market_state(
        source, tmp_path / "market.parquet",
        start=str(dates[-1].date()), end=str(dates[-1].date()),
        history_start=str(dates[0].date()), post_v27_contract=True,
    )
    assert len(result) == 1
    row = result.iloc[0]
    assert row.n20 == 1 and row.n60 == 1
    assert row.market_median_ret20 == (160 / 140 - 1)
    assert row.market_median_ret60 == (160 / 100 - 1)
    assert row.market_regime == "BULL"


def test_v27_capacity_keeps_only_top_twenty_new_entries_per_sleeve() -> None:
    frame = pd.DataFrame({
        "event_id": [f"E{i:02d}" for i in range(21)],
        "symbol": [f"{i:06d}.SZ" for i in range(21)],
        "sleeve": "MAIN",
        "entry_date": pd.Timestamp("2025-01-02"),
        "exit_date": pd.Timestamp("2025-01-10"),
        "exit_reason": "H20_TIME_STOP",
        "rank1": np.arange(21, dtype=float), "rank2": 0.0, "rank3": 0.0,
    })
    accepted, skipped = apply_capacity(frame)
    assert len(accepted) == 20 and len(skipped) == 1
    assert skipped.iloc[0].event_id == "E00"
    assert skipped.iloc[0].skip_reason == "DAILY_ENTRY_CAP_20"
