from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_brth_001.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/MKT-BRTH-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_brth_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
breadth = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(breadth)


def test_spec_is_strategy_independent_and_usefulness_blind() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    forbidden = " ".join(spec["forbidden_inputs"])
    assert "CHINEXT V1 membership" in forbidden
    assert "CY-011" in forbidden
    assert spec["universe"]["no_strategy_membership"] is True
    assert spec["usefulness_boundary"].startswith("No forecast")
    assert spec["gates"]["no_rescue"].startswith("A failed primary")


def test_only_pre_2024_partitions_are_frozen() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    partitions = list(spec["input"]["selected_partition_sha256"])
    assert len(partitions) == 6
    assert partitions[0].startswith("partition_year=2018")
    assert partitions[-1].startswith("partition_year=2023")
    assert not any(year in path for path in partitions for year in ("2024", "2025", "2026"))


def test_connected_components_use_absolute_redundancy() -> None:
    correlation = pd.DataFrame(
        [[1.0, -0.90, 0.10], [-0.90, 1.0, 0.20], [0.10, 0.20, 1.0]],
        index=["participation", "depth", "transition"],
        columns=["participation", "depth", "transition"],
    )
    assert breadth.connected_components(correlation, 0.85) == [
        ["depth", "participation"],
        ["transition"],
    ]


def test_representation_map_has_all_required_concepts() -> None:
    assert set(breadth.ROLE_MAP) == {
        "participation", "depth", "new_high_low", "momentum", "acceleration",
        "industry_diffusion", "leadership_concentration", "divergence", "transition",
    }


def test_deterministic_retry_inherits_exact_scientific_design() -> None:
    retry_path = ROOT / "research/market_behavior_os_v2/experiments/MKT-BRTH-002_spec.json"
    retry = json.loads(retry_path.read_text(encoding="utf-8"))
    assert retry["inherits_spec_sha256"] == breadth.sha256_file(SPEC)
    assert retry["engineering_only_change"].startswith("DuckDB threads fixed to one")
