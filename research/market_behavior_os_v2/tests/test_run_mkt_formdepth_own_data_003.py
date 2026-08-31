from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_data_003.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_own_data_003_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invalid_retry_control_preserved_science_and_diagnosed_domain() -> None:
    module = _module()
    control = json.loads(module.SPEC_PATH.read_text(encoding="utf-8"))
    assert module.base.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["diagnosed_first_difference"][
        "unbound_right_censored_date_cells"
    ] == 36
    assert control["exact_inheritance"][
        "all_001_scientific_definitions_and_input_hashes"
    ] is True
    assert control["exact_inheritance"][
        "all_002_resource_limits_including_3_gib_peak_rss"
    ] is True


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-003_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "MKT-FORMDEPTH-OWN-DATA-003"
    assert result["response_domain"]["stratum_count_exhaustion"] is True
    assert result["response_domain"]["stratum_response_exhaustion"] is True
    assert result["own_shared_association_computed"] is False
    assert result["channel_classification_computed"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
