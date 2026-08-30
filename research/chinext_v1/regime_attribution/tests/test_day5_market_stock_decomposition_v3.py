from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_day5_market_stock_decomposition as base
import run_day5_market_stock_decomposition_v3 as clean


def test_final_clean_identity_and_outputs() -> None:
    assert clean.SPEC.name == "EXP-D5D-003_spec.json"
    assert clean.OUTPUT_JSON.name == "day5_market_stock_decomposition_v3.json"


def test_non_estimable_block_is_not_imputed() -> None:
    blocks = {
        "DEVELOPMENT": {"rho": 0.2},
        "EXTENDED": {"rho": 0.3},
        "HOLDOUT": {"rho": None},
    }
    values = clean.estimable_block_rho_values(blocks)
    assert values == [0.2, 0.3]
    assert len(values) != 3


def test_malformed_block_packet_still_fails_closed() -> None:
    with pytest.raises(base.DecompositionError):
        clean.estimable_block_rho_values({"A": {"p_value": None}})
