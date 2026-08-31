from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_hab_chx_selection_screen_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("selection_screen_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contract_binds_fixed_pre_2024_screen() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert len(spec["screens"]) == 7
    assert "r20 - rs.r120" in spec["screens"]["relative_strength_acceleration"]["field"]
    assert "not signal-time predictors" in spec["exit_diagnostic"]
    assert "post-2023 rows or outcomes" in spec["prohibited"]


def test_result_has_fixed_counts_and_one_advanced_replay() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/HAB-CHX-SELECTION-SCREEN-001_result.json").read_text()
    )
    assert result["completed_trip_counts"] == {
        "development_2018_2021": 194,
        "consumed_2022_2023": 94,
    }
    episodes = result["relative_strength_acceleration_episode_check"]
    assert episodes["supported_episode_count"] == 11
    assert episodes["adverse_episode_count"] == 10
    assert list(result["decisions"].values()).count("ADVANCE_ONE_FIXED_REPLAY") == 1
    assert result["claim_boundary"]["post_2023_rows_read_by_experiment"] is False
