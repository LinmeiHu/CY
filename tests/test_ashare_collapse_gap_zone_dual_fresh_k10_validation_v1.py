import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
PREFIX = "ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-K10-VALIDATION-V1"


def test_frozen_validation_artifacts_and_conservation() -> None:
    result = json.loads((OS_ROOT / f"artifacts/{PREFIX}_result.json").read_text())
    assert result["spec_sha256"] == "59fcb4e98c1adb96b23182a13979b1858dc33a622caa923b884cc3a613dbf194"
    assert result["verdict"] == "DUAL_FRESH_K10_VALIDATION_MIXED"
    assert result["repository_2024_plus_data_opened"] is False
    assert all(value == 0 for key, value in result["audit"].items() if key.endswith("_count"))

    trades = pd.read_parquet(OS_ROOT / f"artifacts/{PREFIX}_trades.parquet")
    assert len(trades) == 94
    assert not trades.event_id.duplicated().any()
    assert not trades.precompleted_before_entry.any()
    assert not trades.risk_blocked_entry.any()
    completed = trades.loc[trades.exit_date.notna()]
    assert (pd.to_datetime(completed.exit_date) > pd.to_datetime(completed.entry_date)).all()
    assert pd.to_datetime(trades.entry_date).dt.year.isin([2022, 2023]).all()

    main = pd.read_parquet(OS_ROOT / f"artifacts/{PREFIX}_main_nav.parquet")
    chinext = pd.read_parquet(OS_ROOT / f"artifacts/{PREFIX}_chinext_nav.parquet")
    assert main.trade_date.equals(chinext.trade_date)
    combined = 0.5 * main.nav.to_numpy() + 0.5 * chinext.nav.to_numpy()
    assert np.isclose(combined[-1] - 1, result["summary"]["COMBINED"]["total_return"], rtol=0, atol=1e-12)
    assert main.active_positions.max() <= 10
    assert chinext.active_positions.max() <= 10
    assert main.cash.min() >= -1e-12
    assert chinext.cash.min() >= -1e-12
