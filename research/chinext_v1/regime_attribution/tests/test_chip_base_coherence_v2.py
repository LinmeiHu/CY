from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_chip_base_coherence as frozen_v1
import run_chip_base_coherence_v2 as clean_v2


def test_v2_changes_only_execution_identity_and_explicit_argument() -> None:
    source = Path(clean_v2.__file__).read_text(encoding="utf-8")
    assert "extra_controls=()" in source
    assert clean_v2.OUTPUT_JSON.name == "chip_base_coherence_attribution_v2.json"
    assert frozen_v1.DISCOVERY_END == pd.Timestamp("2023-12-31")
    assert "chip_base_coherence" in source
    assert "2024_2026_REMAINS_LOCKED" in source
