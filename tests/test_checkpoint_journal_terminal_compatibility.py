from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cyq_game.chip.checkpoint_journal_writer import activate_production_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_counted_terminal_is_usable_by_freeze_assemble_and_merge_consumers() -> None:
    temp = Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase4_", dir="/tmp"))
    annual = temp / "annual" / "year=2020"
    try:
        summary = activate_production_bundle(SOURCE, annual)
        terminals = tuple(annual.glob("terminal/bucket=*/*.parquet"))
        assert len(terminals) == 3
        assert sum(path.stat().st_size for path in terminals) == summary[
            "compatibility_terminal_bytes"
        ]

        freeze = _module(
            "freeze_current_chip_asset_phase4",
            ROOT / "scripts/freeze_current_chip_asset.py",
        )
        verified = freeze._verify_year(temp / "annual", 2020, "2020-12-31")
        assert verified["storage_version"] == "chip-checkpoint-journal-storage-v1"
        assert verified["terminal_files"] == 3

        assembled = temp / "assembled"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/assemble_real_chip_multiyear_root.py"),
                "--output",
                str(assembled),
                "--year-root",
                f"2020={annual}",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assembly = json.loads((assembled / "assembly.json").read_text(encoding="utf-8"))
        assert assembly["storage_version"] == "chip-checkpoint-journal-storage-v1"
        assert len(tuple(assembled.glob("year=2020/terminal/bucket=*/*.parquet"))) == 3

        merged = temp / "merged"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/merge_real_chip_year_roots.py"),
                "--year",
                "2020",
                "--output",
                str(merged),
                "--source",
                str(annual),
                "--expected-files",
                "3",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        merged_summary = json.loads(
            (merged / "summary.json").read_text(encoding="utf-8")
        )
        assert merged_summary["compatibility_terminal_only"] is True
        assert len(tuple(merged.glob("terminal/bucket=*/*.parquet"))) == 3
    finally:
        shutil.rmtree(temp)
