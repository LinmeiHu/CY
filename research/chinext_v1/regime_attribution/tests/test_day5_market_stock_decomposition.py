from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_day5_market_stock_decomposition as decomposition


def test_contract_uses_one_exact_day5_decomposition() -> None:
    assert decomposition.OUTPUT_TABLE.name == "day5_market_stock_decomposition.csv"
    assert decomposition.INDEX.name == "399102_daily.csv"
    assert "return_5d" not in decomposition.BASE_CONTROLS
    assert len(decomposition.BASE_CONTROLS) == 10


def test_scientific_components_are_fixed() -> None:
    source = Path(decomposition.__file__).read_text(encoding="utf-8")
    assert "stock_specific_day5_excess" in source
    assert "beta_adjusted_day5_excess" in source
    assert "int(index) + 4" in source
    assert "DAY5_SESSION_15:30_ASIA_SHANGHAI" in source
