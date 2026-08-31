from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_attr_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_attr_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_boundary_and_activation() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["response"]["primary"] == "adverse_mean_log_excursion_h3"
    assert spec["response"]["terminal_return_read"] is False
    assert spec["controls"]["variable_selection"] is False
    assert "CY-011" in "|".join(spec["prohibited_computations"])


def test_accepted_result_passes_every_fixed_gate_without_strategy_access() -> None:
    result = json.loads(
        (PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_result.json").read_text()
    )
    assert result["classification"] == "INCREMENTAL_OBJECTIVE_FORMATION_TAIL_RISK"
    assert result["evaluation"]["geometry"]["pass"] is True
    assert result["evaluation"]["response"]["pass"] is True
    assert all(result["evaluation"]["response"]["checks"].values())
    assert result["support"]["complete_primary_rows"] == 6631
    assert result["evaluation"]["response"]["same_sign_cells"] == 8
    assert result["strategy_fields_read"] is False
    assert result["post_2023_read"] is False
    assert result["cy011_read"] is False


def test_durable_panel_contains_no_terminal_response() -> None:
    columns = pd.read_csv(
        PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_panel.csv", nrows=0
    ).columns
    assert not any(column.startswith("terminal_") for column in columns)
    assert sorted(
        column for column in columns if column.startswith("adverse_")
    ) == [
        "adverse_mean_log_excursion_h1",
        "adverse_mean_log_excursion_h3",
        "adverse_mean_log_excursion_h5",
    ]
