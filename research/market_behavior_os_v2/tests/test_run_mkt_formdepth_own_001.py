from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_own_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_promote_boundary_has_two_channels_and_no_subgroup_search() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["research_level"] == "PROMOTE"
    assert spec["activation"]["strata"] == 5
    assert spec["shared_channel"]["minimum_passing_strata_for_broad_channel"] == 4
    assert spec["response"]["terminal_return_read"] is False
    prohibited = "|".join(spec["prohibited_computations"])
    assert "subgroup" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited
    assert "terminal_log_return" not in inspect.getsource(module)


def test_exhaustive_classification_uses_only_own_and_broad_shared() -> None:
    module = _module()
    spec = module._load_spec()
    assert (
        module._classification(True, 4, spec)
        == "OWN_AND_BROAD_SHARED_FORMATION_DOWNSIDE"
    )
    assert (
        module._classification(False, 5, spec)
        == "BROAD_SHARED_FORMATION_ENVIRONMENT_ONLY"
    )
    assert module._classification(True, 3, spec) == "OWN_OVERSHOOT_CHANNEL_ONLY"
    assert (
        module._classification(False, 0, spec)
        == "OWN_SHARED_ATTRIBUTION_NOT_RESOLVED"
    )


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["research_level"] == "PROMOTE"
    assert result["classification"] == "OWN_OVERSHOOT_CHANNEL_ONLY"
    assert result["own_channel"]["pass"] is True
    assert all(result["own_channel"]["checks"].values())
    assert result["own_channel"]["negative_cell_medians"] == 8
    assert result["shared_channel"]["passing_strata"] == [1, 2]
    assert result["shared_channel"]["broad_pass"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["terminal_return_read"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
