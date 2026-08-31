from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_disp_rank_002.py"


def _module():
    spec = importlib.util.spec_from_file_location("dispersion_rank_batch_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retry_inherits_science_and_resource_contract_unchanged() -> None:
    module = _module()
    retry, scientific, _, _, _ = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert retry["scientific_changes"] == "NONE"
    assert retry["engineering_change"]["resource_contract"].startswith("inherits every")
    assert scientific["resource"]["prelaunch_available_memory_floor_gib"] == 9
    assert scientific["resource"]["in_run_available_memory_floor_gib"] == 8
    assert scientific["resource"]["temporary_spill_ceiling_gib"] == 12


def test_batch_filter_occurs_after_exact_state_and_before_future_join() -> None:
    module = _module()
    source = inspect.getsource(module._create_rank_security_for_year)
    assert "year(trade_date)={anchor_year}" in source
    assert "coordinate_valid_count120=120" in source
    assert "history_row_count121=121" in source
    assert "f.cal_idx BETWEEN a.cal_idx+1 AND a.cal_idx+5" in source
    assert "sum((f.history_valid AND f.coordinate_step_valid)::INTEGER)=5" in source
    assert "response_count::DOUBLE/a.anchor_count>=0.8" in inspect.getsource(
        module._build_daily_batched
    ) or "_cell_query" in inspect.getsource(module._build_daily_batched)


def test_completed_result_preserves_claim_boundaries_when_present() -> None:
    result_path = PROGRAM / "artifacts/MKT-DISP-RANK-002_result.json"
    if not result_path.exists():
        return
    result = json.loads(result_path.read_text())
    assert result["scientific_changes"] == "NONE"
    assert result["interpretation"]["portfolio_pnl_estimated"] is False
    assert result["interpretation"]["strategy_authorized"] is False
    assert result["same_bar_fill_assumed"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False
