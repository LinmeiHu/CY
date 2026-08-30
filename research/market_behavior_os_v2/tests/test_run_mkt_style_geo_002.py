from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_geo_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_geo_002", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
geometry = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(geometry)


def test_frozen_control_and_parent_identities() -> None:
    spec = geometry._load_spec()
    assert geometry.sha256_file(geometry.SPEC_PATH) == geometry.EXPECTED_SPEC_SHA256
    assert (
        geometry.sha256_file(geometry.PARENT_SPEC_PATH)
        == geometry.EXPECTED_PARENT_SPEC_SHA256
    )
    assert spec["experiment_id"] == "MKT-STYLE-GEO-002"
    assert spec["relative_rank_semantics"]["coordinate"] == "relative_rank"


def test_corrected_relative_rank_support_uses_complete_four_view_dates() -> None:
    spec = geometry._load_spec()
    panel, _ = geometry.load_bound_inputs(spec)
    support = geometry.complete_support_audit(
        panel, spec, geometry._role_fields(spec), geometry._control_fields(spec)
    )
    for role in spec["required_style_roles"]:
        cells = support[role]["relative_rank"]
        assert len(cells) == 6
        assert min(
            item["jointly_nondegenerate_four_view_dates"] for item in cells.values()
        ) >= 150


def test_daily_cross_view_spearman_recovers_same_ordering() -> None:
    frame = pd.DataFrame(
        {
            "target": [0.25, 0.50, 0.75, 1.00],
            "control": [0.25, 0.50, 0.75, 1.00],
        }
    )
    assert geometry._spearman(frame, "target", "control") == 1.0


def test_adjusted_within_date_r2_removes_date_levels() -> None:
    dates = pd.date_range("2021-01-01", periods=50, freq="D")
    rows = []
    for position, date in enumerate(dates):
        level = float(position * 100)
        for view in range(4):
            x1 = float(view)
            x2 = float((view * 3 + position) % 4)
            rows.append(
                {
                    "trade_date": date,
                    "target": level + 2.0 * x1 - 0.5 * x2,
                    "x1": level + x1,
                    "x2": -level + x2,
                }
            )
    observed = geometry.adjusted_within_date_r2(
        pd.DataFrame(rows), "target", ["x1", "x2"]
    )
    assert observed > 0.99


def test_completed_artifact_boundaries_when_present() -> None:
    if not geometry.RESULT_PATH.exists() or not geometry.PANEL_PATH.exists():
        return
    result = json.loads(geometry.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["future_values_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_controls_or_style_roles_read"] == []
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert geometry.sha256_file(geometry.PANEL_PATH) == result["hashes"]["panel_sha256"]
