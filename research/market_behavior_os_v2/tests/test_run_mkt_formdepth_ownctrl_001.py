from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_ownctrl_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_ownctrl_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_promote_boundary_uses_only_five_fixed_controls() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["research_level"] == "PROMOTE"
    assert spec["fixed_same_day_controls"]["variable_selection"] is False
    assert spec["fixed_same_day_controls"]["true_liquidity_claim"] is False
    assert spec["response"]["terminal_return_read"] is False
    prohibited = "|".join(spec["prohibited_computations"])
    assert "minute data" in prohibited
    assert "strategy outcome" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited
    source = inspect.getsource(module._security_frame)
    assert "terminal" not in source
    assert "minute" not in source


def test_date_statistics_residualize_fixed_rank_controls() -> None:
    module = _module()
    size = 40
    axis = np.arange(size, dtype=float)
    frame = pd.DataFrame(
        {
            "own_depth": axis + np.sin(axis),
            "adverse_log_excursion_h3": -axis + np.cos(axis),
            "action_coordinate_close_return": np.sin(axis / 3),
            "intraday_log_range": 1 + np.cos(axis / 5),
            "close_location": (axis % 7) / 7,
            "turnover_fraction": 0.01 + (axis % 11) / 100,
            "log_traded_value": 10 + np.sqrt(axis + 1),
        }
    )
    result = module._date_statistics(frame, 3)
    assert set(result) == {
        "raw_rho",
        "partial_rho",
        "target_rank_r2",
        "low_n",
        "high_n",
        "controlled_tail_gap",
    }
    assert np.isfinite(result["raw_rho"])
    assert np.isfinite(result["partial_rho"])
    assert np.isfinite(result["target_rank_r2"])
    assert np.isfinite(result["controlled_tail_gap"])
    assert result["low_n"] == 8
    assert result["high_n"] == 8
    assert result["partial_rho"] < 0


def test_completed_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-FORMDEPTH-OWNCTRL-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["research_level"] == "PROMOTE"
    assert result["classification"] in {
        "OBJECTIVE_SPECIFIC_OWN_OVERSHOOT_DOWNSIDE",
        "OWN_EFFECT_NOT_INCREMENTAL_TO_FIXED_DAILY_GEOMETRY",
        "SECURITY_LEVEL_OBJECTIVE_SPECIFICITY_NOT_ESTIMABLE",
    }
    assert result["security_level_durable_output"] is False
    assert result["future_response_used_as_predictor"] is False
    assert result["terminal_return_read"] is False
    assert result["minute_data_read"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
