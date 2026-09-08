from __future__ import annotations

import argparse
import json
from pathlib import Path

from .errors import ReproductionError
from .io import load_input_config
from .reproduce import comparisons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy", required=True, choices=("OGR", "IFCGR", "MCB", "ATRDR", "SMV6")
    )
    parser.add_argument("--golden-config", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    target = args.output_root / args.strategy.lower()
    table = comparisons(args.strategy, target, load_input_config(args.golden_config, prefix=args.strategy.lower() + "_"))
    if table.empty:
        raise ReproductionError(f"{args.strategy}: no configured golden comparisons")
    table.to_csv(target / "golden_manifest.csv", index=False)
    failed = table.loc[table.status.ne("PASS")]
    print(json.dumps({
        "strategy": args.strategy,
        "layers": len(table),
        "status": "PASS" if failed.empty else "FAIL",
        "first_difference": None if failed.empty else failed.iloc[0].first_difference,
    }, ensure_ascii=False, indent=2, default=str))
    return 0 if failed.empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
