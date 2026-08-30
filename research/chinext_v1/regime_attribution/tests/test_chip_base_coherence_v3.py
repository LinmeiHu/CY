from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_chip_base_coherence_v3 as exact


def test_exact_loyo_contains_only_discovery_years() -> None:
    frame = pd.DataFrame(
        {
            "entry_year": [2020] * 10 + [2021] * 10 + [2022] * 10 + [2023] * 10,
            "feature": list(range(40)),
            "endpoint": list(range(40)),
        }
    )
    result = exact.rank_association_exact(frame, "feature", "endpoint")
    assert tuple(int(year) for year in result["loyo"]) == exact.DISCOVERY_YEARS
    assert result["loyo_positive_count"] == 4


def test_contract_floor_and_fresh_outputs() -> None:
    assert exact.MIN_CONTROLLED_N == 120
    assert exact.OUTPUT_JSON.name == "chip_base_coherence_attribution_v3.json"
    source = Path(exact.__file__).read_text(encoding="utf-8")
    assert "range(2018, 2026)" not in source
    assert "2024_2026_REMAINS_LOCKED" in source
