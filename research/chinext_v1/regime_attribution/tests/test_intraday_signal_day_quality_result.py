from __future__ import annotations

import hashlib
import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exp_ibq_002_rejected_with_exact_population_and_outputs() -> None:
    result_path = WORK / "artifacts/intraday_signal_day_quality_v2.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["experiment_id"] == "EXP-IBQ-002"
    assert result["decision"] == "REJECTED"
    assert result["population"] == {
        "all_completed_cycles": 399,
        "false_breakout": 213,
        "primary_disjoint_population": 297,
        "primary_fixed_control_complete": 286,
        "success_opportunity20": 84,
    }
    assert not any(result["gates"].values())
    assert result["audit"]["raw_bar_rows"] == 96_159
    assert result["audit"]["maximum_relative_opening_window_difference"] == 0.0
    assert sha256(WORK / "artifacts/intraday_signal_day_quality_v2.csv") == (
        "b503ec0c50a4960cbc7281c68c134eb2a4999416835cae03bc67c2559036646f"
    )
    assert sha256(result_path) == (
        "c7b70809e00694364b7e94a9deac9fb9865b7dc9be8de0a5244d155c43296c12"
    )
