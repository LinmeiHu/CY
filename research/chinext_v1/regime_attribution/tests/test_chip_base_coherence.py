from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_chip_base_coherence as coherence


def test_composite_orients_concentration_retention_and_migration() -> None:
    frame = pd.DataFrame(
        {
            "entry_year": [2020, 2020],
            "cyqk_close_pre": [10.0, 10.0],
            "i90_width_pct": [0.50, 0.10],
            "i70_width_pct": [0.30, 0.05],
            "i90_base_retention": [0.40, 0.90],
            "i70_base_retention": [0.50, 0.95],
            "average_cost_delta": [-0.10, 0.20],
        }
    )
    result = coherence.build_composites(frame)
    assert result.loc[1, "chip_base_coherence"] > result.loc[0, "chip_base_coherence"]
    assert result.loc[1, "upward_cost_migration"] == pytest.approx(0.02)


def test_contract_locks_discovery_and_fresh_outputs() -> None:
    source = Path(coherence.__file__).read_text(encoding="utf-8")
    assert coherence.DISCOVERY_END == pd.Timestamp("2023-12-31")
    assert "2024-01-01..2026-08-12" in source
    assert coherence.OUTPUT_JSON.name == "chip_base_coherence_attribution.json"
    assert "breadth_composite" in coherence.BASE_CONTROLS
