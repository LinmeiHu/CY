from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_min_ad_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_ad_001", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
runner = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(runner)


def test_frozen_hypotheses_have_four_unique_accepted_components() -> None:
    spec = runner._load_spec()
    assert list(spec["hypotheses"]) == spec["compression_priority"]
    for definition in spec["hypotheses"].values():
        components = [*definition["positive"], *definition["negative"]]
        assert len(components) == 4
        assert len(set(components)) == 4


def test_selling_absorption_score_respects_frozen_alignment() -> None:
    spec = runner._load_spec()
    _, panel = runner.construct_panel(spec)
    hypothesis = "selling_effort_absorption"
    target = runner.parent._score_field(hypothesis, "median", "mean")
    row = panel.loc[panel[target].notna()].iloc[0]
    aligned = [
        row[runner.parent._pit_field("down_minute_volume_share", "median")],
        row[runner.parent._pit_field("recovery_speed_30bar", "median")],
        row[runner.parent._pit_field("vwap_recovery_count", "median")],
        1.0 - row[runner.parent._pit_field("downside_excursion", "median")],
    ]
    assert np.isclose(row[target], np.mean(aligned), rtol=0.0, atol=1e-15)
    assert row["available_at"].endswith("15:30:00")


def test_complete_run_preserves_claim_boundaries() -> None:
    result = runner.run()
    assert result["population"]["rows"] == 11656
    assert result["population"]["groups"] == 8
    assert result["usefulness_claim"] == "NONE"
    assert result["participant_accumulation_distribution_claim"] == "NONE"
    assert result["future_state_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["raw_minute_rows_read"] == 0
    assert not result["post_2023_data_read"]
    assert not result["cy011_read"]
