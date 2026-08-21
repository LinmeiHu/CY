#!/usr/bin/env python3
"""Build all-market daily PIT-B data; this script never runs a backtest."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from cyq_game.data import DataActivationError, build_daily_pit_b_dataset


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--benchmark", default="csi000300")
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("configs/data_asset_registry.json"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/input_snapshots/CYQ-PREP-2018-2026-20260820.json"),
    )
    args = parser.parse_args()
    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be supplied together")
    try:
        result = build_daily_pit_b_dataset(
            registry_path=args.registry,
            input_manifest_path=args.manifest,
            output_dir=args.output,
            start=args.start,
            end=args.end,
            benchmark=args.benchmark,
        )
    except (DataActivationError, OSError, ValueError) as exc:
        print(json.dumps({"gate_pass": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
