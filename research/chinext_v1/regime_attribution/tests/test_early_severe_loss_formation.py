from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_early_severe_loss_formation as formation


def test_contract_uses_one_fixed_day3_primary() -> None:
    source = Path(formation.__file__).read_text(encoding="utf-8")
    assert formation.OUTPUT_TABLE.name == "early_severe_loss_formation.csv"
    assert "adverse_stock_specific_3d" in source
    assert "adverse_stock_specific_2d" in source
    assert "adverse_stock_specific_5d" in source
    assert "DAY3_SESSION_15:30_ASIA_SHANGHAI" in source


def test_bottom_flag_is_deterministic() -> None:
    frame = pd.DataFrame(
        {"trade_id": ["b", "a", "c"], "realized_pnl": [-2.0, -2.0, 1.0]}
    )
    flag = formation.bottom_flag(frame, 1)
    assert frame.loc[flag, "trade_id"].tolist() == ["a"]
