from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_disp_econ_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_disp_econ_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explore_contract_discloses_post_discovery_and_prohibits_strategy_use() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["research_level"] == "EXPLORE"
    assert "inspected before" in spec["honesty_boundary"]
    assert spec["responses"]["primary"] == (
        "terminal_p90_log_return_h3 - terminal_p10_log_return_h3"
    )
    assert spec["state"]["variable_selection"] is False
    prohibited = "|".join(spec["prohibited_computations"])
    assert "same-bar execution" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited


def test_partial_spearman_removes_fixed_rank_control_channel() -> None:
    module = _module()
    size = 1000
    random = np.random.default_rng(7)
    control = np.arange(size, dtype=float)
    frame = pd.DataFrame(
        {
            "predictor": control + random.normal(0, 100, size),
            "response": control + random.normal(0, 100, size),
            module.CONTROLS[0]: control,
            module.CONTROLS[1]: np.sin(control / 3),
            module.CONTROLS[2]: np.cos(control / 5),
            module.CONTROLS[3]: np.sin(control / 7),
        }
    )
    raw, _ = module._spearman(frame, "predictor", "response")
    partial, _ = module._partial(frame, "predictor", "response")
    assert raw > 0.8
    assert abs(partial) < 0.2


def test_runner_never_uses_future_response_as_predictor() -> None:
    module = _module()
    source = inspect.getsource(module._analyze)
    assert "PRIMARY_PIT" in source
    assert "PRIMARY_RAW" in source
    assert "terminal_p90_log_return_h3" in source
    assert "future_response_used_as_predictor\": False" in inspect.getsource(module)


def test_completed_explore_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-DISP-ECON-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["research_level"] == "EXPLORE"
    assert result["classification"] == (
        "EXPLORE_CANDIDATE_DISPERSION_OPPORTUNITY_PERSISTENCE"
    )
    assert result["candidate_screen"]["pass"] is True
    assert result["primary"]["horizons"]["3"]["positive_partial_cells"] == 8
    assert result["interpretation"]["directional_market_timing_supported"] is False
    assert result["interpretation"]["realizable_long_short_return_estimated"] is False
    assert result["interpretation"]["strategy_authorized"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["same_bar_fill_assumed"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
