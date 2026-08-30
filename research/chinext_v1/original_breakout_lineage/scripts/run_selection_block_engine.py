#!/usr/bin/env python3
"""Run one frozen V1 baseline block for event-only selection reconstruction."""

from __future__ import annotations

import argparse
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for path in (str(SCRIPTS), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from run_chinext_v1_smoke import run  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--warmup-start", type=date.fromisoformat)
    parser.add_argument("--pit-membership", type=Path, required=True)
    parser.add_argument("--daily-root", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    cli = parse_args()
    cli.output_dir.mkdir(parents=True, exist_ok=False)
    arguments = Namespace(
        start=cli.start,
        end=cli.end,
        warmup_start=cli.warmup_start
        if cli.warmup_start is not None
        else date(cli.start.year - 1, 1, 1),
        sample_size=10_000,
        full_survivor=True,
        initial_cash=1_000_000.0,
        pit_membership=cli.pit_membership,
        daily_root=cli.daily_root,
        market=cli.market,
        calendar=cli.calendar,
        summary=cli.output_dir / "engine_summary.json",
        report=cli.output_dir / "engine_report.md",
        output_dir=cli.output_dir,
    )
    run(arguments)


if __name__ == "__main__":
    main()
