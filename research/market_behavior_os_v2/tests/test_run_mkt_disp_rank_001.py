from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_disp_rank_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_disp_rank_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_rank_discriminator_has_action_safe_response_and_no_pnl() -> None:
    module = _module()
    spec, _, _ = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["begins"] == "t+1 exchange session"
    assert spec["response"]["horizons"] == [1, 3, 5]
    assert spec["dispersion_habitat"]["no_other_threshold"] is True
    assert spec["resource"]["in_run_available_memory_floor_gib"] == 8
    prohibited = "|".join(spec["prohibited"])
    assert "security selection or portfolio PnL" in prohibited
    assert "same-bar fill" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited


def test_rank_security_requires_every_intervening_coordinate_step() -> None:
    module = _module()
    source = inspect.getsource(module._create_rank_security)
    assert "count(*)=5" in source
    assert "sum((f.history_valid AND f.coordinate_step_valid)::INTEGER)=5" in source
    assert "f.cal_idx BETWEEN a.cal_idx+1 AND a.cal_idx+5" in source


def test_completed_rank_result_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-DISP-RANK-001_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["classification"] in {
        "HIGH_DISPERSION_INDUSTRY_RANK_CONTINUATION",
        "HIGH_DISPERSION_INDUSTRY_RANK_REVERSAL",
        "HIGH_DISPERSION_DIRECTIONLESS_OR_UNSTABLE_RANKING",
    }
    assert result["interpretation"]["security_selection_estimated"] is False
    assert result["interpretation"]["portfolio_pnl_estimated"] is False
    assert result["interpretation"]["strategy_authorized"] is False
    assert result["same_bar_fill_assumed"] is False
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
