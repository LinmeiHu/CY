from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from cyq_game.chip.checkpoint_journal_writer import activate_production_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"


def test_clean_activation_resume_is_identical_and_stale_partial_root_fails_closed() -> None:
    temporary = Path(
        tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase6_", dir="/tmp")
    )
    output = temporary / "year=2020"
    try:
        clean = activate_production_bundle(SOURCE, output)
        resumed = activate_production_bundle(SOURCE, output)
        assert resumed == clean

        partial = temporary / "partial-year"
        partial.mkdir()
        (partial / "partial-worker-state").write_text("partial", encoding="utf-8")
        with pytest.raises(ValueError, match="resume fingerprint"):
            activate_production_bundle(SOURCE, partial)
        assert (partial / "partial-worker-state").read_text(encoding="utf-8") == "partial"
    finally:
        shutil.rmtree(temporary)
