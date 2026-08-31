from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

PROGRAM = Path(__file__).resolve().parents[1]
SCRIPT = PROGRAM / "scripts/run_ashare_external_prior_cycle_005.py"
RESULT = PROGRAM / "artifacts/ASHARE-EXTERNAL-PRIOR-CYCLE-005_result.json"
MODULE_SPEC = importlib.util.spec_from_file_location("ashare_external_prior_cycle_005", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def test_frozen_prior_cycle_contract_is_bounded_and_consumed_only() -> None:
    spec = MODULE._load_spec()
    assert spec["research_window"] == ["2018-01-02", "2023-12-29"]
    assert len(spec["external_tests"]) == 5
    assert len(spec["internal_tests"]) == 3
    assert len(spec["combination_tests"]) == 2
    assert spec["screen"]["external_maximum_replays"] == 3
    assert spec["screen"]["internal_maximum_replays"] == 1


def test_future_links_stop_at_each_frozen_natural_horizon() -> None:
    start = date(2020, 1, 1)
    calendar = [start + timedelta(days=index) for index in range(130)]
    selections = pd.DataFrame(
        {
            "symbol": ["short", "long", "endpoint"],
            "trade_date": [calendar[0], calendar[0], calendar[-4]],
            "natural_horizon": [5, 120, 20],
        }
    )

    links = MODULE._future_links(selections, calendar)

    assert links.groupby("candidate_row").horizon.max().to_dict() == {0: 5, 1: 120, 2: 3}
    assert len(links) == 128


def test_negative_combination_cannot_be_promoted_for_relative_improvement() -> None:
    rows = []
    for family, track, full, early, late, severe in (
        ("max_lottery_20", "external", -0.011, -0.020, -0.002, 0.02),
        ("max_lottery_plus_low_idio", "combination", -0.007, -0.019, 0.004, 0.01),
    ):
        for period, excess in (
            ("full", full),
            ("early_2018_2020", early),
            ("late_2021_2023", late),
        ):
            rows.append(
                {
                    "family": family,
                    "track": track,
                    "period": period,
                    "horizon": 20,
                    "count": 1_000,
                    "signal_dates": 50,
                    "mean_excess_vs_date_control": excess,
                    "severe_loss_disadvantage": severe,
                    "entry_executable_fraction": 1.0,
                }
            )
    diagnostics = pd.DataFrame(
        {
            "family": ["max_lottery_20", "max_lottery_plus_low_idio"],
            "median_candidates": [2_000.0, 2_000.0],
        }
    )

    decisions = MODULE._screen_decisions({}, pd.DataFrame(rows), diagnostics)
    combination = next(row for row in decisions if row["family"] == "max_lottery_plus_low_idio")

    assert combination["full_excess"] > -0.011
    assert combination["passes_all_screen_gates"] is False
    assert combination["incremental_vs_named_baseline"]["passes"] is False
    assert combination["replay_decision"] == "COMPLEXITY_NOT_EARNED"


def test_checkpoint_result_preserves_no_promotion_boundary() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    assert result["input_audit"]["daily_first"] == "2018-01-02"
    assert result["input_audit"]["daily_last"] == "2023-12-29"
    assert result["input_audit"]["daily_time_travel"] == 0
    assert result["input_audit"]["daily_lineage_failures"] == 0
    assert result["input_audit"]["minute_lineage_failures"] == 0
    assert result["promoted_families"] == []
    assert result["replays"] == []
    assert result["action_audit"] == {"not_run": True}
    assert all(not row["passes_all_screen_gates"] for row in result["decisions"])
