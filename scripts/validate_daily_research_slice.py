#!/usr/bin/env python3
"""Validate one symbol and at most one month of real daily PIT-B inputs."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from cyq_game.data import DataActivationError, prepare_daily_research_slice


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
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
    try:
        result = prepare_daily_research_slice(
            registry_path=args.registry,
            input_manifest_path=args.manifest,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
        )
    except (DataActivationError, OSError, ValueError) as exc:
        print(json.dumps({"gate_pass": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
