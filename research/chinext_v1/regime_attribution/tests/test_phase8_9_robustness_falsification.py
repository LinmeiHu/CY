from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SCRIPT = WORK / "scripts/run_phase8_9_robustness_falsification.py"
RESULT = WORK / "artifacts/v1r_robustness_falsification.json"
MANIFEST = WORK / "artifacts/v1r_candidate_ledger_manifest.json"


def load_module():
    spec = importlib.util.spec_from_file_location("phase8_9", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rolling_records_use_only_within_block_nav() -> None:
    module = load_module()
    dates = pd.date_range("2025-01-01", periods=254, freq="D")
    control = pd.DataFrame({"trade_date": dates, "nav": [100.0] * 254})
    candidate = pd.DataFrame(
        {"trade_date": dates, "nav": [100.0 + index for index in range(254)]}
    )
    rows = module.rolling_records("SYNTHETIC", control, candidate)
    counts = pd.DataFrame(rows).groupby("window_sessions").size().to_dict()
    assert counts == {126: 128, 252: 2}
    first = rows[0]
    assert first["start_date"] == "2025-01-01"
    assert first["end_date"] == dates[126].date().isoformat()
    assert first["control_return"] == 0.0
    assert first["candidate_return"] == pytest.approx(1.26)


def test_frozen_manifest_rehashes_all_fifteen_ledgers() -> None:
    module = load_module()
    _, manifest = module.load_and_validate_spec()
    assert manifest["ledger_count"] == 15
    assert len(manifest["ledgers"]) == 15
    assert {
        (row["block"], row["arm"]) for row in manifest["ledgers"]
    } == {(block, arm) for block in module.BLOCKS for arm in module.ARMS}


def test_phase8_9_result_preserves_negative_and_implementation_evidence() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["strategy_replay_count"] == 0
    assert result["threshold_fit_count"] == 0
    assert result["neighbor_selected_as_primary"] is False
    assert result["naive_nav_chaining"] is False
    assert result["decision"] == {
        "candidate_verdict": "REJECT_V1R_KEEP_FROZEN_V1",
        "hypothesis_h010": "SUPPORTED_EXPLANATORY_ONLY",
        "production_authorized": False,
        "robustness_verdict": "FAIL_NOT_ROBUST",
    }
    gates = result["robustness_gates"]["components"]
    assert gates["right_tail_retention"]["passes"] is True
    assert gates["pit_execution_implementation"]["passes"] is True
    assert gates["yearly"]["passes"] is False
    assert gates["rolling"]["passes"] is False
    assert gates["loyo_no_refit"]["passes"] is False
    assert gates["neighboring_definitions"]["passes"] is False
    checks = result["implementation_audit"]["checks"]
    assert checks["same_day_fill_count"] == 0
    assert checks["feature_timestamp_failure_count"] == 0
    assert checks["new_buy_target_weight_mismatch_count"] == 0
    assert checks["missing_feature_candidate_new_buy_count"] == 0
    assert checks["entry_signal_changes"] == 0
    assert checks["rank_changes"] == 0
    assert checks["exit_changes"] == 0
    assert len(result["falsification_challenges"]) == 10


def test_manifest_artifact_has_expected_identity() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["manifest_id"] == "CHINEXT-V1R-P7-FROZEN-LEDGER-MANIFEST-V1"
    assert manifest["purpose"] == "OUTCOME_BLIND_IDENTITY_BINDING_FOR_PHASE8_9"
