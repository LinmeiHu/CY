#!/usr/bin/env python3
"""Build and validate only the governed V3 five-symbol production sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import build_real_chip_year as builder

from cyq_game.chip.checkpoint_journal_reader import (
    CheckpointJournalReader,
    DependencyCatalog,
)
from cyq_game.chip.checkpoint_journal_writer import (
    activate_production_bundle,
    manifest_coverage,
    regular_file_bytes,
    verify_root,
    write_json,
)
from cyq_game.chip.journal_codec import decode_journal
from cyq_game.chip.peaks import EnsembleTemporalPeakTracker

SYMBOLS = (
    "000001.SZ",
    "002260.SZ",
    "002706.SZ",
    "300604.SZ",
    "600519.SH",
)
TARGET_YEAR = 2020
OLD_V2_SEMANTIC_FINGERPRINT = (
    "424e82a0dd817a8d2c1e618d2929aa58506d8b4336c6c765bf08692adf593518"
)
OLD_V2_ARTIFACT_FINGERPRINT = (
    "58c18585f25b48c07467880d7c6d5a8eba6d8c49d003ae6c9142f91283adca62"
)


def _partition(stage_root: Path, kind: str, symbol: str) -> Path | None:
    matches = tuple(stage_root.glob(f"{kind}/bucket=*/symbol={symbol}"))
    if kind == "minute" and not matches:
        return None
    if len(matches) != 1:
        raise ValueError(
            f"expected one {kind} partition for {symbol}, found {len(matches)}"
        )
    return matches[0]


def _manifest(
    *,
    artifacts: list[Any],
    dependency_manifest_digest: str,
    replay_parameter_manifest_digest: str,
    replay_contract_hash: str,
    terminal_completeness_digest: str,
    semantic_fingerprint: str,
    artifact_contract_fingerprint: str,
    physical_fingerprint: str,
    physical_contract: dict[str, Any],
    git_head: str,
    bundle_id: str,
    root_id: str,
) -> dict[str, Any]:
    return {
        "artifact_version": builder.CHECKPOINT_JOURNAL_ARTIFACT_VERSION,
        "bundle_id": bundle_id,
        "checkpoint_cadence": builder.CHECKPOINT_CADENCE,
        "coverage": manifest_coverage(
            artifacts, bundle_id=bundle_id, root_id=root_id
        ),
        "dependency_manifest_digest": dependency_manifest_digest,
        "manifest_version": "symbol-manifest-v1",
        "parts": [
            part
            for part in builder._checkpoint_journal_manifest_parts(artifacts)
            if part["kind"] in {"checkpoint", "journal", "feature"}
        ],
        "replay_contract_hash": replay_contract_hash,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "root_id": root_id,
        "seller_models": list(builder.CHECKPOINT_JOURNAL_SELLER_MODELS),
        "symbols": list(SYMBOLS),
        "target_year": TARGET_YEAR,
        "terminal_completeness_digest": terminal_completeness_digest,
        "writer_version": builder.PRODUCTION_WRITER_VERSION,
        "resume_contract_version": builder.RESUME_CONTRACT_VERSION,
        "semantic_fingerprint": semantic_fingerprint,
        "artifact_contract_fingerprint": artifact_contract_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "physical_contract": physical_contract,
        "git_head_provenance": git_head,
    }


def build(stage_root: Path, output: Path, *, buffer_rows: int) -> dict[str, Any]:
    stage_root = stage_root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError("five-symbol V3 output already exists")
    if buffer_rows not in builder.BUFFER_CANDIDATES:
        raise ValueError("buffer rows are outside the frozen candidates")
    complete_path = stage_root / "COMPLETE.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if (
        complete.get("year") != TARGET_YEAR
        or complete.get("warmup_start") != 2018
        or complete.get("layout_version")
        != "bucket-symbol-v3-mixed-native-resolution"
    ):
        raise ValueError("governed five-symbol stage contract mismatch")

    daily = {symbol: _partition(stage_root, "daily", symbol) for symbol in SYMBOLS}
    minute = {symbol: _partition(stage_root, "minute", symbol) for symbol in SYMBOLS}
    if any(path is None for path in daily.values()):
        raise AssertionError("daily partition unexpectedly missing")

    run_root = output.parent / f".{output.name}.building"
    if run_root.exists():
        raise ValueError("five-symbol V3 build root already exists")
    candidate_root = run_root / "candidate"
    input_manifest_root = run_root / "input-manifests"
    candidate_root.mkdir(parents=True)
    input_manifest_root.mkdir()

    semantic_fingerprint = builder._semantic_fingerprint_v2()
    artifact_contract_fingerprint = builder._artifact_contract_fingerprint()
    physical_fingerprint = builder._physical_fingerprint(buffer_rows)
    git_head = builder._git_head_provenance()
    dependency_manifest_digest = builder.logical_sha256(
        {
            "daily_root": complete["daily_root"],
            "minute_root": complete["minute_root"],
            "stage_complete_sha256": builder.sha256_file(complete_path),
            "symbols": SYMBOLS,
            "year": TARGET_YEAR,
        }
    )
    replay_parameter_manifest_digest = builder.logical_sha256(
        {
            "checkpoint_cadence": builder.CHECKPOINT_CADENCE,
            "seller_models": builder.CHECKPOINT_JOURNAL_SELLER_MODELS,
            "symbols": SYMBOLS,
            "target_year": TARGET_YEAR,
            "warmup_years": (2018, 2019),
            "writer_version": builder.PHASE2_WRITER_VERSION,
        }
    )
    runtime_fingerprint = builder.logical_sha256(
        {"runtime_contract": "checkpoint-journal-runtime-provenance-separated-v2"}
    )
    replay_contract_hash = builder.logical_sha256(
        {
            "semantic_fingerprint": semantic_fingerprint,
            "artifact_contract_fingerprint": artifact_contract_fingerprint,
            "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        }
    )
    terminal_completeness_digest = builder.logical_sha256(
        {
            "schema_version": builder.TERMINAL_COMPLETENESS_VERSION,
            "policy": "YEAR_END_CHECKPOINT_PLUS_COUNTED_COMPATIBILITY_TERMINAL",
        }
    )
    bundle_id = "v12-rolling-structural-base-v3-5symbol-2020"
    root_id = "v12-rolling-structural-base-v3-5symbol-root-v1"
    common = {
        "year": TARGET_YEAR,
        "candidate_root": str(candidate_root),
        "dependency_manifest_digest": dependency_manifest_digest,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "replay_contract_hash": replay_contract_hash,
        "semantic_fingerprint": semantic_fingerprint,
        "runtime_fingerprint": runtime_fingerprint,
        "terminal_completeness_digest": terminal_completeness_digest,
        "bundle_id": bundle_id,
        "root_id": root_id,
        "stage_root": str(stage_root),
        "input_manifest_root": str(input_manifest_root),
        "artifact_contract_fingerprint": artifact_contract_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "output_buffer_rows": buffer_rows,
        "workers": 1,
        "scheduler": "governed-five-symbol-order",
        "largest_first": False,
        "git_head": git_head,
    }

    results = {}
    for symbol in SYMBOLS:
        results[symbol] = builder._checkpoint_journal_symbol_worker(
            {
                **common,
                "symbol": symbol,
                "daily_path": str(daily[symbol]),
                "minute_path": (
                    None if minute[symbol] is None else str(minute[symbol])
                ),
            }
        )
    artifacts = [
        builder._checkpoint_journal_artifact_from_payload(results[symbol])
        for symbol in SYMBOLS
    ]
    pre_manifest_summary = {
        "symbols": list(SYMBOLS),
        "rows": sum(artifact.trading_days for artifact in artifacts),
        "model_rows": sum(artifact.model_rows for artifact in artifacts),
        "max_mass_error": max(
            float(results[symbol]["result"]["max_mass_error"])
            for symbol in SYMBOLS
        ),
        "max_same_day_resale": max(
            float(results[symbol]["result"]["max_same_day_resale"])
            for symbol in SYMBOLS
        ),
    }
    write_json(candidate_root / "summary.json", pre_manifest_summary)
    root_manifest = _manifest(
        artifacts=artifacts,
        dependency_manifest_digest=dependency_manifest_digest,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        replay_contract_hash=replay_contract_hash,
        terminal_completeness_digest=terminal_completeness_digest,
        semantic_fingerprint=semantic_fingerprint,
        artifact_contract_fingerprint=artifact_contract_fingerprint,
        physical_fingerprint=physical_fingerprint,
        physical_contract=builder._physical_contract(buffer_rows),
        git_head=git_head,
        bundle_id=bundle_id,
        root_id=root_id,
    )
    write_json(candidate_root / "manifest.json", root_manifest)
    verify_root(candidate_root, verify_all_content=True)
    activation = activate_production_bundle(candidate_root, output)
    verify_root(output, verify_all_content=True)

    journal_rows = []
    for part in root_manifest["parts"]:
        if part["kind"] == "journal":
            journal_rows.extend(
                decode_journal((output / part["relative_path"]).read_bytes()).rows
            )
    reader = CheckpointJournalReader(
        output,
        replay_parameter_manifest_digest=replay_parameter_manifest_digest,
        dependency_catalog=DependencyCatalog.from_journal_rows(journal_rows),
    )
    restored_tracker_scopes = {}
    reuse_status = {}
    for symbol in SYMBOLS:
        checkpoint = reader.latest_checkpoint(symbol)
        restored = EnsembleTemporalPeakTracker.from_continuation(
            symbol=symbol, continuation=checkpoint.temporal_tracker
        )
        restored_tracker_scopes[symbol] = len(restored.continuation().scopes)
        input_fingerprint, _ = builder._symbol_input_fingerprint(
            symbol=symbol,
            year=TARGET_YEAR,
            stage_root=stage_root,
            daily_path=daily[symbol],  # type: ignore[arg-type]
            minute_path=minute[symbol],
            manifest_root=input_manifest_root,
        )
        manifest_path = output / f"symbol={symbol}" / "manifest.json"
        base = {
            "manifest_path": manifest_path,
            "candidate_root": output,
            "input_fingerprint": input_fingerprint,
        }
        reuse_status[symbol] = {
            "current": builder._symbol_reuse_status(
                **base,
                semantic_fingerprint=semantic_fingerprint,
                artifact_contract_fingerprint=artifact_contract_fingerprint,
            ),
            "old_semantic": builder._symbol_reuse_status(
                **base,
                semantic_fingerprint=OLD_V2_SEMANTIC_FINGERPRINT,
                artifact_contract_fingerprint=artifact_contract_fingerprint,
            ),
            "old_artifact": builder._symbol_reuse_status(
                **base,
                semantic_fingerprint=semantic_fingerprint,
                artifact_contract_fingerprint=OLD_V2_ARTIFACT_FINGERPRINT,
            ),
        }

    result = {
        **pre_manifest_summary,
        "activation": activation,
        "output": str(output),
        "bytes": regular_file_bytes(output),
        "git_head": git_head,
        "semantic_fingerprint": semantic_fingerprint,
        "artifact_contract_fingerprint": artifact_contract_fingerprint,
        "physical_fingerprint": physical_fingerprint,
        "replay_parameter_manifest_digest": replay_parameter_manifest_digest,
        "root_manifest_sha256": builder.sha256_file(output / "manifest.json"),
        "symbol_manifest_sha256": {
            symbol: builder.sha256_file(
                output / f"symbol={symbol}" / "manifest.json"
            )
            for symbol in SYMBOLS
        },
        "restored_tracker_scopes": restored_tracker_scopes,
        "reuse_status": reuse_status,
    }
    write_json(output.parent / f"{output.name}.validation.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--buffer-rows", type=int, choices=builder.BUFFER_CANDIDATES, default=24
    )
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.stage_root, args.output, buffer_rows=args.buffer_rows),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
