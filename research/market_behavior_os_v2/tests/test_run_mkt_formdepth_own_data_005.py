from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_data_005.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_own_data_005_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_requires_control_clock_only_for_complete_rows() -> None:
    module = _module()
    effective = module._load_spec()
    control = effective["_control_clock_retry_control"]
    parent = json.loads(module.PARENT_SPEC.read_text(encoding="utf-8"))
    assert module.base.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert control["invalid_parent"]["outputs_accepted"] is False
    assert control["diagnosed_domain"][
        "right_censored_cells_without_control_clock"
    ] == 36
    assert control["diagnosed_domain"]["complete_cells_without_control_clock"] == 0
    assert effective["resource_budget"]["peak_rss_ceiling_gib"] == 3.0
    assert effective["resource_budget"]["duckdb_memory_limit_gib"] == 1.5
    assert effective["membership"] == parent["membership"]
    assert effective["response"] == parent["response"]
    assert effective["support"] == parent["support"]
    assert effective["prohibited_computations"] == parent["prohibited_computations"]


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-005_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    domain = result["response_domain"]
    assert result["experiment_id"] == "MKT-FORMDEPTH-OWN-DATA-005"
    assert domain["stratum_count_exhaustion"] is True
    assert domain["stratum_response_exhaustion"] is True
    assert domain["structurally_right_censored_date_cells"] == 36
    assert domain["right_censored_rows_without_control_clock"] == 180
    assert result["own_shared_association_computed"] is False
    assert result["channel_classification_computed"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
