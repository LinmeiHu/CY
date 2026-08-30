from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_risk_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_risk_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
risk = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(risk)


def test_signed_limit_utilization_uses_each_registered_side_without_clipping() -> None:
    frame = pd.DataFrame({
        "close": [11.0, 9.0, 10.0, 12.01, 8.0],
        "preclose": [10.0] * 5,
        "up_limit_price": [12.0] * 5,
        "down_limit_price": [8.0] * 5,
        "limit_pct": [0.20] * 5,
    })
    actual = risk.signed_limit_utilization(frame)
    assert actual.iloc[0] == 0.5
    assert actual.iloc[1] == -0.5
    assert actual.iloc[2] == 0.0
    assert np.isnan(actual.iloc[3])
    assert actual.iloc[4] == -1.0


def test_signed_limit_utilization_fails_unknown_or_invalid_geometry_closed() -> None:
    frame = pd.DataFrame({
        "close": [10.0, 10.0, 10.0],
        "preclose": [10.0, 10.0, 10.0],
        "up_limit_price": [10.0, 11.0, 11.0],
        "down_limit_price": [9.0, 9.0, 9.0],
        "limit_pct": [0.10, np.nan, 0.30],
    })
    assert risk.signed_limit_utilization(frame).isna().all()


def test_frozen_spec_hash_and_role_map_match() -> None:
    expected = "7b5303c38b278b042a7d0fabea653e7c78c3f5e781cfcaf5847a36a28c2764a8"
    assert hashlib.sha256(risk.SPEC_PATH.read_bytes()).hexdigest() == expected
    spec = json.loads(risk.SPEC_PATH.read_text(encoding="utf-8"))
    assert list(spec["representations"]) == list(risk.ROLE_MAP)
    assert spec["engineering"]["duckdb_threads"] == 1
    assert "MKT-SHOCK-001 score" in spec["forbidden_inputs"][4]


def test_completed_artifact_preserves_boundaries_when_present() -> None:
    if not risk.PANEL_PATH.exists() or not risk.RESULT_PATH.exists():
        return
    panel = pd.read_csv(risk.PANEL_PATH)
    result = json.loads(risk.RESULT_PATH.read_text(encoding="utf-8"))
    assert panel["trade_date"].max() <= "2023-12-31"
    assert panel.loc[panel["view_valid"], "limit_eligible_fraction"].min() >= 0.99
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["shock_score_read"] is False
    assert result["usefulness_claim"] == "NONE"
    if {"upside_extreme_participation", "downside_extreme_participation"}.issubset(
        result["minimal_panel"]["accepted_roles"]
    ):
        assert result["minimal_panel"]["excluded_roles"]["tail_risk_appetite_balance"].startswith(
            "deterministic_composite_of:"
        )
    assert result["hashes"]["panel_sha256"] == hashlib.sha256(risk.PANEL_PATH.read_bytes()).hexdigest()
