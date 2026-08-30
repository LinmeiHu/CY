from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_entry_cohort_crowding as cohort


def test_primary_is_cohort_date_artifact() -> None:
    assert cohort.OUT_TABLE.name == "entry_cohort_crowding.csv"
    assert "breadth_composite" in cohort.CONTROL_COLS


def test_frozen_result_rejects_positive_crowding_mechanism() -> None:
    result = json.loads(cohort.OUT_JSON.read_text())
    primary = result["primary"]
    assert result["decision"] == "REJECT"
    assert result["audit"]["cohort_dates"] == 255
    assert result["audit"]["pseudoreplicated_primary"] is False
    assert primary["cohort_date_raw"]["rho"] < 0
    assert primary["cohort_date_raw"]["loyo_positive_count"] == 0
    assert primary["controlled"]["partial_rank_rho"] < 0
    assert primary["controlled"]["loyo_positive_count"] == 0
    assert not any(
        primary[name]
        for name in (
            "raw_gate",
            "controlled_gate",
            "neighbor_gate",
            "topology_gate",
            "falsification_gate",
        )
    )
