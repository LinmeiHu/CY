from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

PROGRAM = Path(__file__).resolve().parents[1]
SCRIPT = PROGRAM / "scripts/run_ashare_fundamental_readiness_cycle_006.py"
RESULT = PROGRAM / "artifacts/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_result.json"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "ashare_fundamental_readiness_cycle_006", SCRIPT
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def test_fundamental_track_fails_closed_before_internal_outcomes() -> None:
    spec = MODULE._load_spec()

    assert spec["starting_checkpoint"] == "18a3282ebc"
    assert spec["fundamental_track"]["status"] == "PIT_FUNDAMENTAL_DATA_BLOCKED"
    assert spec["fundamental_track"]["tested_priors"] == []
    assert len(spec["internal_tests"]) == 3
    assert spec["combinations"]["maximum"] == 0


def test_severe_control_uses_individual_control_names_not_date_mean() -> None:
    rows = []
    for family, leg, net_returns in (
        ("date_control", "control", [-0.20, 0.00]),
        ("test_family", "top", [-0.15]),
    ):
        for index, net_return in enumerate(net_returns):
            rows.append(
                {
                    "family": family,
                    "leg": leg,
                    "trade_date": "2020-01-31",
                    "status_h20": "COMPLETE",
                    "net_return_h20": net_return,
                    "gross_return_h20": net_return + 0.004,
                    "entry_status": "EXECUTABLE",
                    "candidate_count": 100,
                    "avg_amount20": 100_000_000,
                    "entry_amount_h20": 10_000_000 + index,
                }
            )

    summary = MODULE._summary(pd.DataFrame(rows))
    top = summary.iloc[0]

    assert top["control_severe_loss_fraction"] == 0.5
    assert top["severe_loss_fraction"] == 1.0
    assert top["severe_loss_disadvantage"] == 0.5


def test_checkpoint_result_has_no_fundamental_proxy_or_promotion() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))

    assert result["fundamental_track"]["status"] == "PIT_FUNDAMENTAL_DATA_BLOCKED"
    assert result["fundamental_track"]["tested_priors"] == []
    assert result["acquisition"]["performed"] is False
    assert result["acquisition"]["bytes_written"] == 0
    assert result["input_audit"]["time_travel"] == 0
    assert result["input_audit"]["lineage_failures"] == 0
    assert result["promoted_families"] == []
    assert result["replays"] == []
    assert result["combinations"] == []
