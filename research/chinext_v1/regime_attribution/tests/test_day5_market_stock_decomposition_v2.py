from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_day5_market_stock_decomposition as base
import run_day5_market_stock_decomposition_v2 as clean


def test_clean_identity_and_fresh_outputs() -> None:
    assert clean.SPEC.name == "EXP-D5D-002_spec.json"
    assert clean.OUTPUT_TABLE.name == "day5_market_stock_decomposition_v2.csv"
    assert clean.OUTPUT_JSON.name == "day5_market_stock_decomposition_v2.json"


def test_block_gate_extracts_rank_packet_rho() -> None:
    blocks = {
        "A": {"rho": 0.2, "p_value": 0.1},
        "B": {"rho": -0.01, "p_value": 0.9},
        "C": {"rho": 0.3, "p_value": 0.01},
    }
    assert clean.block_rho_values(blocks) == [0.2, -0.01, 0.3]


def test_block_gate_fails_closed_on_malformed_packet() -> None:
    with pytest.raises(base.DecompositionError):
        clean.block_rho_values({"A": {"p_value": 0.1}})
