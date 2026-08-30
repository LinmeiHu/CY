from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_clq_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-CLQ-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_clq_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
clq = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(clq)


def test_spec_is_strategy_and_usefulness_blind() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    forbidden = " ".join(spec["forbidden_inputs"])
    assert "CHINEXT V1 membership" in forbidden
    assert "future returns" in forbidden
    assert "CY-011" in forbidden
    assert spec["universe"]["no_strategy_membership"] is True
    assert spec["usefulness_boundary"].startswith("No panic")


def test_liquidity_units_and_pre_2024_inputs_are_frozen() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["input"]["eligible_positive_amount_rows"] == 5_814_399
    assert spec["input"]["eligible_valid_turnover_rows"] == 5_814_399
    assert spec["input"]["eligible_amount_scale_failures_above_3_decimals"] == 0
    assert spec["input"]["maximum_turnover_unit_difference"] < 1e-12
    partitions = list(spec["input"]["selected_partition_sha256"])
    assert len(partitions) == 6
    assert not any(year in path for path in partitions for year in ("2024", "2025", "2026"))


def test_representation_map_separates_required_roles() -> None:
    assert set(clq.ROLE_MAP) == {
        "co_movement", "directional_synchronization", "liquidity_activity",
        "liquidity_participation", "turnover_level", "liquidity_concentration",
        "industry_liquidity_diffusion", "liquidity_change",
    }


def test_connected_components_use_absolute_spearman() -> None:
    correlation = pd.DataFrame(
        [[1.0, -0.90, 0.1], [-0.90, 1.0, 0.2], [0.1, 0.2, 1.0]],
        index=["co_movement", "directional_synchronization", "liquidity_activity"],
        columns=["co_movement", "directional_synchronization", "liquidity_activity"],
    )
    assert clq.connected_components(correlation) == [
        ["co_movement", "directional_synchronization"],
        ["liquidity_activity"],
    ]
