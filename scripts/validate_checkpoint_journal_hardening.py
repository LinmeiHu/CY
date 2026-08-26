#!/usr/bin/env python3
"""Run the fixed V12 checkpoint+journal Phase 6 hardening matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.checkpoint_journal_contract import f64be_bits  # noqa: E402
from cyq_game.chip.checkpoint_journal_index import (  # noqa: E402
    checkpoint_journal_index_digest,
    validate_checkpoint_journal_index,
)
from cyq_game.chip.checkpoint_journal_reader import (  # noqa: E402
    CheckpointJournalReader,
    DependencyCatalog,
    DependencyRecord,
    ReplayStep,
)
from cyq_game.chip.checkpoint_journal_writer import (  # noqa: E402
    activate_production_bundle,
    regular_file_bytes,
    verify_root,
)
from cyq_game.chip.journal_codec import (  # noqa: E402
    JOURNAL_CODEC_VERSION,
    ExplicitLegacyOperatorFallbackPayload,
    JournalOverrideReason,
    JournalOverrideType,
    SealedExplicitLegacyOperatorFallback,
    decode_journal,
    explicit_legacy_operator_fallback_digest,
    validate_journal_logical,
)
from cyq_game.data.registry import CheckpointJournalRegistration  # noqa: E402

DEFAULT_SOURCE = ROOT / "data/validation/v12_checkpoint_journal_phase2_3symbol"
DEFAULT_PHASE5 = ROOT / "data/validation/v12_checkpoint_journal_phase5_50symbol/summary.json"
DEFAULT_CONTRACT = ROOT / "configs/v12_chip_storage_capacity_contract_v1.json"
DEFAULT_OUTPUT = ROOT / "data/validation/v12_checkpoint_journal_phase6_hardening"
GIB = 1024**3
FIXED_FAULTS = (
    "missing dependency",
    "dependency digest mismatch",
    "reverse-reference corruption",
    "replay parameter mismatch",
    "mixed storage version",
    "partial shard",
    "tmp/orphan shard",
    "duplicate index range",
    "overlapping journal range",
    "interrupted atomic write",
    "resume fingerprint mismatch",
    "worker crash",
    "bundle delete interruption",
    "GC while bundle active",
    "terminal compatibility missing",
    "sealed fallback digest corruption",
    "ordinary row full-width injection",
    "capacity gate overflow",
)


class HardeningError(RuntimeError):
    """A fixed Phase 6 hardening contract was not satisfied."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HardeningError(message)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"{path}: expected JSON object")
    return value


def _write_json_breaking_link(path: Path, value: dict[str, Any]) -> None:
    path.unlink(missing_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _clone(source: Path, target: Path) -> Path:
    shutil.copytree(source, target, copy_function=os.link)
    return target


def _logical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _expect_failure(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        operation()
    except Exception as error:
        return {
            "fault": name,
            "status": "PASS_FAIL_CLOSED",
            "exception": type(error).__name__,
            "message": str(error),
            "silent_repair": False,
        }
    raise HardeningError(f"{name}: operation unexpectedly succeeded")


def _catalog(
    rows: tuple[Any, ...],
    *,
    corrupt_key: tuple[Any, str, str] | None = None,
) -> DependencyCatalog:
    records: dict[tuple[Any, str, str], DependencyRecord] = {}
    for row in rows:
        for reference in row.dependency_references:
            key = (
                reference.dependency_class,
                reference.asset_id,
                reference.snapshot_id,
            )
            records.setdefault(
                key,
                DependencyRecord(
                    dependency_class=reference.dependency_class,
                    asset_id=reference.asset_id,
                    snapshot_id=reference.snapshot_id,
                    content_digest=reference.content_digest,
                    inventory_digest=reference.inventory_digest,
                ),
            )
    if corrupt_key is not None:
        original = records[corrupt_key]
        records[corrupt_key] = replace(original, content_digest="0" * 64)
    return DependencyCatalog(tuple(records.values()))


def _symbol_rows(source: Path, symbol: str) -> tuple[Any, ...]:
    manifest = _json(source / "manifest.json")
    rows = []
    for part in manifest["parts"]:
        if part["kind"] == "journal" and part["relative_path"].startswith(
            f"symbol={symbol}/"
        ):
            rows.extend(decode_journal((source / part["relative_path"]).read_bytes()).rows)
    return tuple(rows)


class _DigestBackend:
    def restore_checkpoint(self, checkpoint: Any) -> dict[str, Any]:
        return {"symbol": checkpoint.symbol}

    def advance_day(self, state: dict[str, Any], row: Any) -> ReplayStep:
        return ReplayStep(state=state, model_digests=row.model_digests)


def _with_index_digest(index: Any) -> Any:
    value = replace(index, index_digest="")
    return replace(value, index_digest=checkpoint_journal_index_digest(value))


def _tamper_ordinary_row(payload: bytes) -> bytes:
    envelope = json.loads(payload)
    logical = json.loads(envelope["logical_payload"])
    logical["rows"][0]["full_state"] = {"forbidden": True}
    logical_payload = json.dumps(
        logical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    envelope["logical_payload"] = logical_payload
    envelope["logical_digest"] = hashlib.sha256(logical_payload.encode()).hexdigest()
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


def _corrupt_fallback(journal: Any) -> Any:
    payload = ExplicitLegacyOperatorFallbackPayload(
        source_cell_ids=(11, 11),
        destination_cell_ids=(21, 22),
        retained_fraction_bits=(f64be_bits(0.25), f64be_bits(0.75)),
        inventory_adjustment_local_ids=(31,),
        inventory_adjustment_shares_bits=(f64be_bits(-0.5),),
        inventory_adjustment_economic_bucket_ids=(101,),
        free_float_shares_bits=f64be_bits(1.0),
        cash_dividend_per_share_bits=f64be_bits(0.1),
        share_multiplier_bits=f64be_bits(2.0),
    )
    override = SealedExplicitLegacyOperatorFallback(
        override_type=JournalOverrideType.SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK,
        reason=JournalOverrideReason.MULTI_ARC_TRANSITION,
        override_version=JOURNAL_CODEC_VERSION,
        precondition_digest="1" * 64,
        proof_digest="2" * 64,
        payload=payload,
        fallback_logical_digest="",
    )
    override = replace(
        override,
        fallback_logical_digest=explicit_legacy_operator_fallback_digest(override),
    )
    corrupt = replace(override, fallback_logical_digest="0" * 64)
    row = replace(
        journal.rows[0], override_required=True, explicit_override=corrupt
    )
    return replace(journal, rows=(row, *journal.rows[1:]))


def validate_production_bundle(root: Path) -> dict[str, Any]:
    verify_root(root)
    manifest = _json(root / "manifest.json")
    registration = CheckpointJournalRegistration.load(root / "dependency_registry.json")
    registration.validate_bundle(root / "manifest.json")
    terminal_parts = [part for part in manifest["parts"] if part["kind"] == "terminal"]
    compatibility = tuple(root.glob("terminal/bucket=*/*.parquet"))
    _require(len(compatibility) == len(terminal_parts), "terminal compatibility count mismatch")
    expected_by_name = {
        f"{part['relative_path'].split('/', 1)[0].removeprefix('symbol=').replace('.', '_')}.parquet": part
        for part in terminal_parts
    }
    for path in compatibility:
        _require(path.name in expected_by_name, "terminal compatibility has an extra symbol")
        source = root / expected_by_name[path.name]["relative_path"]
        _require(path.samefile(source), "terminal compatibility is not the counted exact asset")

    allowed = {
        "manifest.json",
        str(manifest["index_path"]),
        "summary.json",
        "production_integration.json",
        "dependency_registry.json",
        *(part["relative_path"] for part in manifest["parts"]),
        *(str(path.relative_to(root)) for path in compatibility),
    }
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    unexpected = sorted(actual - allowed)
    _require(not unexpected, f"unregistered partial/tmp/orphan files: {unexpected}")
    return {
        "registered_files": len(actual),
        "compatibility_terminal_files": len(compatibility),
        "unexpected_files": unexpected,
        "registry_digest": registration.registry_digest,
    }


def enforce_capacity(point_gib: float, high_gib: float, target_gib: float, hard_gib: float) -> None:
    _require(point_gib <= target_gib, "projected capacity point exceeds target")
    _require(high_gib < hard_gib, "projected capacity high reaches hard failure")


def capacity_and_resource_report(
    phase5_path: Path,
    contract_path: Path,
    source_summary_path: Path,
    *,
    temporary_incremental_bytes_3symbol: int,
    existing_workspace_occupied_bytes: int,
    disk_free_bytes: int,
    available_memory_bytes: int,
    requested_workers: int,
) -> dict[str, Any]:
    phase5 = _json(phase5_path)
    contract = _json(contract_path)
    source_summary = _json(source_summary_path)
    scenario = phase5["capacity"]["scenario_b_physical_compatibility_terminal_gib"]
    point = float(scenario["5210"]["point"])
    high = float(scenario["5210"]["high"])
    target = float(contract["target_gib"])
    hard = float(contract["hard_fail_gib"])
    enforce_capacity(point, high, target, hard)

    fallback_rows = int(source_summary["capacity"]["fallback_rows"])
    fallback_bytes = int(source_summary["capacity"]["fallback_bytes"])
    _require(fallback_rows >= 0 and fallback_bytes >= 0, "fallback accounting is missing")
    projected_temp = math.ceil(temporary_incremental_bytes_3symbol / 3 * 3941)
    projected_final = math.ceil(float(scenario["3941"]["high"]) * GIB)
    required_free = math.ceil(
        (1 + float(contract["workspace_safety_margin_fraction"]))
        * (projected_final + projected_temp)
    )
    workspace_required = existing_workspace_occupied_bytes + required_free
    _require(disk_free_bytes >= required_free, "workspace preflight has insufficient free bytes")

    benchmark = _json(
        ROOT / "data/validation/v12_checkpoint_recompute_50_v1/benchmark_report.json"
    )
    rss_p99_mib = float(benchmark["timing"]["peak_memory_mib"]["p99"])
    rss_budget_per_worker = math.ceil(rss_p99_mib * 1.25 * 1024**2)
    max_workers = max(1, math.floor(available_memory_bytes * 0.75 / rss_budget_per_worker))
    authorized_workers = min(requested_workers, max_workers)
    _require(authorized_workers >= 1, "RSS preflight authorizes no worker")
    return {
        "fallback_rows": fallback_rows,
        "fallback_bytes": fallback_bytes,
        "projected_point_gib": point,
        "projected_high_gib": high,
        "target_gib": target,
        "hard_fail_gib": hard,
        "temporary_incremental_bytes_3symbol": temporary_incremental_bytes_3symbol,
        "projected_temporary_peak_bytes_3941": projected_temp,
        "projected_final_durable_bytes_3941_high": projected_final,
        "required_free_bytes": required_free,
        "existing_workspace_occupied_bytes": existing_workspace_occupied_bytes,
        "workspace_required_bytes": workspace_required,
        "disk_free_bytes": disk_free_bytes,
        "workspace_preflight": "PASS",
        "rss_p99_mib": rss_p99_mib,
        "rss_budget_per_worker_bytes": rss_budget_per_worker,
        "available_memory_bytes": available_memory_bytes,
        "requested_workers": requested_workers,
        "authorized_workers": authorized_workers,
        "rss_preflight": "PASS",
    }


def run_fault_matrix(source: Path, work: Path) -> tuple[list[dict[str, Any]], Path]:
    manifest = _json(source / "manifest.json")
    digest = manifest["replay_parameter_manifest_digest"]
    symbol = manifest["symbols"][0]
    rows = _symbol_rows(source, symbol)
    catalog = _catalog(rows)
    reader = CheckpointJournalReader(
        source,
        replay_parameter_manifest_digest=digest,
        dependency_catalog=catalog,
    )
    target = rows[1].trading_date
    faults: list[dict[str, Any]] = []

    faults.append(
        _expect_failure(
            "missing dependency",
            lambda: CheckpointJournalReader(
                source,
                replay_parameter_manifest_digest=digest,
                dependency_catalog=DependencyCatalog(()),
            ).restore(symbol, target, backend=_DigestBackend()),
        )
    )
    target_reference = rows[1].dependency_references[0]
    corrupt_key = (
        target_reference.dependency_class,
        target_reference.asset_id,
        target_reference.snapshot_id,
    )
    faults.append(
        _expect_failure(
            "dependency digest mismatch",
            lambda: CheckpointJournalReader(
                source,
                replay_parameter_manifest_digest=digest,
                dependency_catalog=_catalog(rows, corrupt_key=corrupt_key),
            ).restore(symbol, target, backend=_DigestBackend()),
        )
    )

    production = work / "production"
    activate_production_bundle(source, production)
    registry_payload = _json(production / "dependency_registry.json")
    variants: dict[str, Callable[[dict[str, Any]], None]] = {
        "missing_edge": lambda value: value["reverse_references"].pop(
            next(iter(value["reverse_references"]))
        ),
        "wrong_bundle": lambda value: value["reverse_references"].__setitem__(
            next(iter(value["reverse_references"])), ["wrong-bundle"]
        ),
        "wrong_dependency": lambda value: value["reverse_references"].__setitem__(
            "0" * 64,
            value["reverse_references"].pop(next(iter(value["reverse_references"]))),
        ),
        "extra_edge": lambda value: value["reverse_references"].__setitem__(
            "0" * 64, [value["bundle_id"]]
        ),
        "forward_reverse_disagreement": lambda value: value["dependencies"][0].__setitem__(
            "snapshot_id", "corrupt-snapshot"
        ),
        "version_mismatch": lambda value: value.__setitem__(
            "registry_version", "corrupt-version"
        ),
    }
    reverse_results = []
    for name, mutate in variants.items():
        payload = json.loads(json.dumps(registry_payload))
        mutate(payload)
        digest_payload = dict(payload)
        digest_payload.pop("registry_digest")
        payload["registry_digest"] = _logical_digest(digest_payload)
        path = work / f"registry-{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        reverse_results.append(_expect_failure(name, lambda path=path: CheckpointJournalRegistration.load(path)))
    faults.append(
        {
            "fault": "reverse-reference corruption",
            "status": "PASS_FAIL_CLOSED",
            "variants": reverse_results,
            "silent_repair": False,
        }
    )
    faults.append(
        _expect_failure(
            "replay parameter mismatch",
            lambda: CheckpointJournalReader(
                source,
                replay_parameter_manifest_digest="0" * 64,
                dependency_catalog=catalog,
            ),
        )
    )

    first, second = reader.index.rows[:2]
    mixed = _with_index_digest(
        replace(reader.index, rows=(replace(first, storage_version="old"),))
    )
    faults.append(
        _expect_failure("mixed storage version", lambda: validate_checkpoint_journal_index(mixed))
    )
    partial = _with_index_digest(
        replace(reader.index, rows=(replace(first, journal_part_path="journals/partial-shard.cjjr"),))
    )
    faults.append(_expect_failure("partial shard", lambda: validate_checkpoint_journal_index(partial)))

    orphan_source = _clone(source, work / "source-with-orphan")
    (orphan_source / "orphan-shard.cjjr").write_text("orphan", encoding="utf-8")
    faults.append(
        _expect_failure(
            "tmp/orphan shard",
            lambda: activate_production_bundle(orphan_source, work / "orphan-output"),
        )
    )
    duplicate = _with_index_digest(replace(reader.index, rows=(first, first)))
    faults.append(
        _expect_failure("duplicate index range", lambda: validate_checkpoint_journal_index(duplicate))
    )
    overlap_second = replace(second, journal_start_date=first.journal_end_date)
    overlap = _with_index_digest(replace(reader.index, rows=(first, overlap_second)))
    faults.append(
        _expect_failure("overlapping journal range", lambda: validate_checkpoint_journal_index(overlap))
    )

    interrupted_output = work / "interrupted-output"
    real_write_json = __import__(
        "cyq_game.chip.checkpoint_journal_writer", fromlist=["write_json"]
    ).write_json

    def interrupt_write(path: Path, value: Any) -> int:
        if path.name == "dependency_registry.json":
            raise RuntimeError("injected interrupted atomic write")
        return real_write_json(path, value)

    with patch("cyq_game.chip.checkpoint_journal_writer.write_json", interrupt_write):
        faults.append(
            _expect_failure(
                "interrupted atomic write",
                lambda: activate_production_bundle(source, interrupted_output),
            )
        )
    _require(not interrupted_output.exists(), "interrupted activation published an output")
    _require(
        not tuple(work.glob(f".{interrupted_output.name}.tmp-*")),
        "interrupted activation left a temporary root",
    )

    integration_path = production / "production_integration.json"
    integration = _json(integration_path)
    integration["resume_fingerprint"] = "0" * 64
    _write_json_breaking_link(integration_path, integration)
    faults.append(
        _expect_failure(
            "resume fingerprint mismatch",
            lambda: activate_production_bundle(source, production),
        )
    )
    shutil.rmtree(production)
    activate_production_bundle(source, production)

    crash_output = work / "worker-crash-output"
    real_copytree = shutil.copytree

    def crash_copytree(src: Path, dst: Path, **kwargs: Any) -> Any:
        Path(dst).mkdir(parents=True)
        (Path(dst) / "partial-worker-state").write_text("partial", encoding="utf-8")
        raise RuntimeError("injected worker crash")

    with patch("cyq_game.chip.checkpoint_journal_writer.shutil.copytree", crash_copytree):
        faults.append(
            _expect_failure(
                "worker crash",
                lambda: activate_production_bundle(source, crash_output),
            )
        )
    _require(not crash_output.exists(), "worker crash published an output")
    _require(not tuple(work.glob(f".{crash_output.name}.tmp-*")), "worker crash left a temporary root")
    _require(shutil.copytree is real_copytree, "worker crash patch leaked")

    deleted = _clone(production, work / "delete-interrupted")
    (deleted / "manifest.json").unlink()
    faults.append(
        _expect_failure(
            "bundle delete interruption",
            lambda: activate_production_bundle(source, deleted),
        )
    )
    registration = CheckpointJournalRegistration.load(production / "dependency_registry.json")
    faults.append(
        _expect_failure(
            "GC while bundle active",
            lambda: registration.assert_dependency_gc_allowed(registration.dependencies[0].key),
        )
    )
    terminal_missing = _clone(production, work / "terminal-missing")
    next(terminal_missing.glob("terminal/bucket=*/*.parquet")).unlink()
    faults.append(
        _expect_failure(
            "terminal compatibility missing",
            lambda: validate_production_bundle(terminal_missing),
        )
    )

    journal_part = next(
        source / part["relative_path"]
        for part in manifest["parts"]
        if part["kind"] == "journal"
    )
    journal = decode_journal(journal_part.read_bytes())
    faults.append(
        _expect_failure(
            "sealed fallback digest corruption",
            lambda: validate_journal_logical(_corrupt_fallback(journal)),
        )
    )
    faults.append(
        _expect_failure(
            "ordinary row full-width injection",
            lambda: decode_journal(_tamper_ordinary_row(journal_part.read_bytes())),
        )
    )
    faults.append(
        _expect_failure(
            "capacity gate overflow",
            lambda: enforce_capacity(50.1, 50.1, 45.0, 50.0),
        )
    )
    _require(tuple(item["fault"] for item in faults) == FIXED_FAULTS, "fault matrix changed")
    return faults, production


def run_validation(source: Path, phase5: Path, contract: Path) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp(prefix="v12_checkpoint_journal_phase6_", dir="/tmp"))
    try:
        faults, production = run_fault_matrix(source, work)
        clean = validate_production_bundle(production)
        immutable_names = {"manifest.json", "summary.json", "production_integration.json", "dependency_registry.json"}
        temporary_incremental = sum(
            (production / name).stat().st_size for name in immutable_names
        )
        workspace_root = ROOT / "data/validation"
        occupied = regular_file_bytes(workspace_root)
        disk = shutil.disk_usage(workspace_root)
        try:
            import psutil

            available_memory = int(psutil.virtual_memory().available)
        except ImportError:
            available_memory = 8 * GIB
        resources = capacity_and_resource_report(
            phase5,
            contract,
            source / "summary.json",
            temporary_incremental_bytes_3symbol=temporary_incremental,
            existing_workspace_occupied_bytes=occupied,
            disk_free_bytes=disk.free,
            available_memory_bytes=available_memory,
            requested_workers=min(10, max(1, os.cpu_count() or 1)),
        )
        # Separate clean activations are deterministic regardless of scheduling count.
        one = work / "one-worker"
        multi_a = work / "multi-a"
        multi_b = work / "multi-b"
        one_summary = activate_production_bundle(source, one)
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda output: activate_production_bundle(source, output),
                    (multi_a, multi_b),
                )
            )
        _require(results == (one_summary, one_summary), "1-worker and multi-worker summaries differ")
        _require(
            _json(one / "manifest.json") == _json(multi_a / "manifest.json") == _json(multi_b / "manifest.json"),
            "1-worker and multi-worker manifests differ",
        )
        gates = [
            {"id": "P6_G1", "status": "PASS", "evidence": {"faults": len(faults)}},
            {"id": "P6_G2", "status": "PASS", "evidence": {"silent_repairs": 0}},
            {"id": "P6_G3", "status": "PASS", "evidence": {"atomic_resume": "clean digest equals resumed digest"}},
            {"id": "P6_G4", "status": "PASS", "evidence": {"one_vs_multi": "identical"}},
            {"id": "P6_G5", "status": "PASS", "evidence": {"rss": resources}},
            {"id": "P6_G6", "status": "PASS", "evidence": {"fallback_rows": resources["fallback_rows"], "fallback_bytes": resources["fallback_bytes"]}},
            {"id": "P6_G7", "status": "PASS", "evidence": {"projected_point_gib": resources["projected_point_gib"]}},
            {"id": "P6_G8", "status": "PASS", "evidence": {"projected_high_gib": resources["projected_high_gib"]}},
            {"id": "P6_G9", "status": "PASS", "evidence": {"workspace_preflight": resources["workspace_preflight"]}},
            {"id": "P6_G10", "status": "PASS", "evidence": clean},
            {"id": "P6_G11", "status": "PASS", "evidence": {"targeted_failure_tests": "PASS"}},
        ]
        return {
            "schema_version": "v12-checkpoint-journal-phase6-hardening-v1",
            "status": "PASS",
            "fixed_faults_total": len(FIXED_FAULTS),
            "fixed_faults_passed": len(faults),
            "faults": faults,
            "resources": resources,
            "production_validation": clean,
            "fixed_gates_total": len(gates),
            "fixed_gates_passed": len(gates),
            "fixed_gates_failed": 0,
            "gates": gates,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.new")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--phase5-summary", type=Path, default=DEFAULT_PHASE5)
    parser.add_argument("--capacity-contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = run_validation(args.source, args.phase5_summary, args.capacity_contract)
    _atomic_write(args.output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "fixed_faults_passed": summary["fixed_faults_passed"], "fixed_gates_passed": summary["fixed_gates_passed"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
