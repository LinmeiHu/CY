from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_immed_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_immed_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_two_sided_immediacy_boundary() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["primary_horizon"] == 3
    assert spec["response"]["neighbor_horizon"] == 5
    assert spec["two_sided_gates"]["minimum_absolute_median_h3_partial_rho"] == 0.1
    assert spec["two_sided_gates"]["minimum_absolute_tail_residual_gap"] == 0.02
    assert "CY-011" in "|".join(spec["prohibited_computations"])


def test_immediacy_fails_without_future_predictor_or_strategy_access() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-IMMED-001_result.json").read_text()
    )
    checks = result["evaluation"]["checks"]
    assert result["classification"] == "NO_STABLE_TROUGH_IMMEDIACY_SHIFT"
    assert result["evaluation"]["pass"] is False
    assert checks["primary"] is False
    assert checks["blocks"] is False
    assert checks["years"] is False
    assert checks["neighbor"] is False
    assert checks["h5_phases"] is False
    assert result["future_trough_used_as_predictor"] is False
    assert result["habitat_action"] == "NONE"
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
