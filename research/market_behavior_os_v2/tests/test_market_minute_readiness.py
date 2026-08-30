from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/audit_market_minute_readiness.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/AUDIT-MKT-MIN-001_spec.json"
MODULE_SPEC = importlib.util.spec_from_file_location("audit_market_minute_readiness", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
minute = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(minute)


def test_spec_is_strategy_independent_and_outcome_blind() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["outcome_access"] is False
    assert spec["sample"]["expected_trajectories"] == 240
    assert spec["sample"]["expected_sessions"] == 1200
    assert "minute facts prohibited" in spec["sample"]["selection_source"]
    assert "CY-011" in " ".join(spec["forbidden_inputs"])


def test_deterministic_order_is_stable_and_view_specific() -> None:
    import pandas as pd
    anchor = pd.Timestamp("2020-06-15")
    first = minute.deterministic_order(anchor, "ALL_A", "000001.SZ")
    assert first == minute.deterministic_order(anchor, "ALL_A", "000001.SZ")
    assert first != minute.deterministic_order(anchor, "SZ_A", "000001.SZ")


def test_only_pre_2024_partitions_are_selected() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    selected = sum(spec["selected_partitions"].values(), [])
    assert not any(year in path for path in selected for year in ("2024", "2025", "2026"))
