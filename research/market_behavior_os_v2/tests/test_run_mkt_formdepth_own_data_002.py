from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_data_002.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_own_data_002_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invalid_retry_control_changed_only_measured_rss_and_output() -> None:
    module = _module()
    control = json.loads(module.SPEC_PATH.read_text(encoding="utf-8"))
    assert module.base.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["invalid_parent"]["association_or_adequacy_inspected"] is False
    assert control["only_changes"]["peak_rss_ceiling_gib_from"] == 1.5
    assert control["only_changes"]["peak_rss_ceiling_gib_to"] == 3.0
    assert control["global_admission"]["duckdb_memory_limit_gib"] == 1.5
    assert control["exact_inheritance"]["all_scientific_definitions"] is True
    assert control["exact_inheritance"]["all_support_and_scalar_gates"] is True


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-002_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "MKT-FORMDEPTH-OWN-DATA-002"
    assert result["own_shared_association_computed"] is False
    assert result["channel_classification_computed"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
