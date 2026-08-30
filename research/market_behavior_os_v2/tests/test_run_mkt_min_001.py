from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
minute = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(minute)


def test_view_masks_are_strategy_independent_and_nested() -> None:
    symbols = pd.Series(["600000.SH", "000001.SZ", "300001.SZ", "301001.SZ"])
    masks = minute._view_masks(symbols)
    assert masks["ALL_A"].tolist() == [True, True, True, True]
    assert masks["SH_A"].tolist() == [True, False, False, False]
    assert masks["SZ_A"].tolist() == [False, True, True, True]
    assert masks["CHINEXT_BOARD"].tolist() == [False, False, True, True]


def test_resource_contract_keeps_25_percent_ram_headroom() -> None:
    assert minute.RAM_FLOOR_BYTES >= 8 * 1024**3
    assert minute.RSS_CEILING_BYTES <= 3 * 1024**3
    assert minute.MINIMUM_COUNTS == {
        "ALL_A": 1000,
        "SH_A": 400,
        "SZ_A": 400,
        "CHINEXT_BOARD": 200,
    }
