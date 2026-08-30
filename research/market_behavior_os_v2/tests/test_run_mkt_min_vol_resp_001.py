from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_vol_resp_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_vol_resp_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
respmod = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(respmod)


def test_frozen_spec_and_input_hashes() -> None:
    spec = respmod._load_spec()
    assert respmod.sha256_file(respmod.SPEC_PATH) == respmod.EXPECTED_SPEC_SHA256
    assert respmod.sha256_file(respmod.PARENT_SPEC_PATH) == respmod.EXPECTED_PARENT_SPEC_SHA256
    paths = respmod._input_paths(spec)
    assert respmod.sha256_file(paths["geometry_panel"]) == spec["inputs"]["geometry_panel"]["sha256"]
    assert respmod.sha256_file(paths["daily_minute_panel"]) == spec["inputs"]["daily_minute_panel"]["sha256"]
    assert spec["temporal_blocks"]["confirmation"] == ["2022-01-01", "2023-12-29"]
    assert spec["response"]["domain_rule"].startswith("construct log")


def test_partial_rank_correlation_recovers_residual_relation() -> None:
    control = np.tile([0.0, 1.0], 15)
    target = np.arange(30, dtype=float)
    outcome = target + control * 0.1
    frame = pd.DataFrame({"target": target, "outcome": outcome, "control": control})
    assert respmod.partial_rank_correlation(frame, "target", "outcome", ["control"]) > 0.8


def test_bound_inputs_preserve_exact_current_lineage() -> None:
    spec = respmod._load_spec()
    geometry, daily = respmod.load_bound_inputs(spec)
    assert len(geometry) == 10696
    panel = respmod.construct_forward_responses(geometry, daily, spec)
    assert panel[spec["controls"][0]].equals(panel["lineage_current_minute_level"])
    for horizon in (1, 3, 5):
        valid = panel[f"response_date_h{horizon}"].notna()
        assert (panel.loc[valid, f"response_date_h{horizon}"] > panel.loc[valid, "trade_date"]).all()


def test_forward_shift_is_by_group_session() -> None:
    spec = respmod._load_spec()
    geometry, daily = respmod.load_bound_inputs(spec)
    panel = respmod.construct_forward_responses(geometry, daily, spec)
    group = panel.loc[(panel.market_view == "ALL_A") & (panel.denominator == "ALL_STATUS")].sort_values("trade_date")
    assert group.iloc[0]["response_date_h5"] == group.iloc[5]["trade_date"]
    assert pd.isna(group.iloc[-1]["response_available_at_h5"])


def test_completed_artifact_boundaries_when_present() -> None:
    if not respmod.RESULT_PATH.exists() or not respmod.PANEL_PATH.exists():
        return
    result = json.loads(respmod.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["raw_minute_rows_read"] == 0
    assert result["future_market_price_returns_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["strategy_usefulness_claim"] == "NONE"
    assert respmod.sha256_file(respmod.PANEL_PATH) == result["hashes"]["panel_sha256"]
