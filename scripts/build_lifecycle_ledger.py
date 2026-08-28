#!/usr/bin/env python3
"""Build the deterministic post-hoc lifecycle ledger from frozen V3 inputs."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from cyq_game.strategy.lifecycle_ledger import (
    FIVE_SYMBOLS,
    _sha256,
    accepted_strategy_parameters,
    build_frozen_v3_panel,
    ledger_provenance,
    ledger_tables_sha256,
    load_and_validate_freeze,
    prepare_ledger_config,
    prepare_read_only_lineage_view,
    replay_frozen_panel,
    verify_frozen_files,
    write_ledger_artifacts,
)
from cyq_game.strategy.markup_retest import MarkupRetestConfig


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("five", "full"), required=True)
    parser.add_argument("--frozen-root", type=Path, required=True)
    parser.add_argument("--freeze-lock", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--lineage-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--implementation-commit")
    return parser.parse_args()


def _head() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> None:
    args = _arguments()
    if args.work_root.exists():
        raise FileExistsError(f"work root already exists: {args.work_root}")
    if args.output_root.exists():
        raise FileExistsError(f"output root already exists: {args.output_root}")
    parameters = accepted_strategy_parameters()
    base_config = MarkupRetestConfig.load(args.config)
    if args.mode == "full":
        _, lock, symbols = load_and_validate_freeze(
            frozen_root=args.frozen_root,
            freeze_lock_path=args.freeze_lock,
            parameters=parameters,
        )
        before = verify_frozen_files(args.frozen_root, lock)
    else:
        lock = {}
        symbols = FIVE_SYMBOLS
        before = {"root_manifest_sha256": _sha256(args.frozen_root / "manifest.json")}

    lineage_view = prepare_read_only_lineage_view(
        source_root=args.lineage_root,
        work_root=args.work_root,
    )
    config = prepare_ledger_config(
        base_config,
        symbols=symbols,
        lineage_root=lineage_view,
    )
    panel_path, panel_metadata = build_frozen_v3_panel(
        config=config,
        frozen_root=args.frozen_root,
        symbols=symbols,
        work_root=args.work_root,
    )
    provenance = ledger_provenance(
        config=config,
        implementation_commit=args.implementation_commit or _head(),
    )

    fresh_result = None
    if args.mode == "five":
        fresh_result, _ = replay_frozen_panel(
            config=config,
            panel_path=panel_path,
            symbols=symbols,
            provenance=provenance,
            collect_ledger=False,
        )
    replay_a, tables_a = replay_frozen_panel(
        config=config,
        panel_path=panel_path,
        symbols=symbols,
        provenance=provenance,
    )
    replay_b, tables_b = replay_frozen_panel(
        config=config,
        panel_path=panel_path,
        symbols=symbols,
        provenance=provenance,
    )
    table_sha_a = ledger_tables_sha256(tables_a)
    table_sha_b = ledger_tables_sha256(tables_b)
    if replay_a != replay_b or table_sha_a != table_sha_b:
        raise RuntimeError("repeat replay is not exactly deterministic")
    if fresh_result is not None and fresh_result != replay_a:
        raise RuntimeError("fresh production replay and observed ledger replay diverged")

    if args.mode == "full":
        after = verify_frozen_files(args.frozen_root, lock)
    else:
        after = {"root_manifest_sha256": _sha256(args.frozen_root / "manifest.json")}
    if before != after:
        raise RuntimeError("frozen input bytes changed during ledger replay")
    freeze_verification = {"before": before, "after": after, "unchanged": True}

    repeat_artifacts = write_ledger_artifacts(
        output_root=args.work_root / "repeat_artifacts",
        tables=tables_b,
        provenance=provenance,
        panel_metadata=panel_metadata,
        freeze_verification=freeze_verification,
    )
    artifacts = write_ledger_artifacts(
        output_root=args.output_root,
        tables=tables_a,
        provenance=provenance,
        panel_metadata=panel_metadata,
        freeze_verification=freeze_verification,
    )
    if artifacts.artifact_hashes != repeat_artifacts.artifact_hashes:
        raise RuntimeError("deterministic Parquet artifact hashes differ across replay")
    result = {
        "mode": args.mode,
        "symbols": len(symbols),
        "input_rows": replay_a.input_rows,
        "evaluation_rows": replay_a.evaluation_rows,
        "signals": len(replay_a.signals),
        "trades": len(replay_a.trades),
        "open_exposures": len(replay_a.open_exposures),
        "fresh_equivalent": fresh_result == replay_a if fresh_result is not None else None,
        "repeat_exact": True,
        "ledger_tables_sha256": table_sha_a,
        "artifact_result": {
            **asdict(artifacts),
            "output_root": str(artifacts.output_root),
            "manifest_path": str(artifacts.manifest_path),
        },
        "freeze_verification": freeze_verification,
    }
    print(json.dumps(result, sort_keys=True, indent=2, default=str))


if __name__ == "__main__":
    main()
