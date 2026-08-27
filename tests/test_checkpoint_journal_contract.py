from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import subprocess
import sys
import zlib
from dataclasses import fields, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

import numpy as np
import pytest

import cyq_game.chip.checkpoint_journal_writer as checkpoint_writer
from cyq_game.chip.checkpoint_codec import (
    checkpoint_logical_digest,
    decode_checkpoint,
    encode_checkpoint,
)
from cyq_game.chip.checkpoint_compact_codec import (
    PRODUCTION_CHECKPOINT_CODEC_VERSION,
    decode_compact_checkpoint,
)
from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    CHECKPOINT_CODEC_VERSION,
    DEPENDENCY_BINDING_VERSION,
    DEPENDENCY_MANIFEST_VERSION,
    EXPECTED_REPLAY_PARAMETER_OWNER_VERSIONS,
    FROZEN_REPLAY_PARAMETER_VALUES,
    QUALITY_REASON_CODE_DOMAIN_VERSION,
    REPLAY_PARAMETER_MANIFEST_VERSION,
    REQUIRED_REPLAY_PARAMETER_NAMES,
    RESEARCH_RECOVERABLE_REASON_CODES,
    SCHEMA_VERSION,
    SELLER_MODEL_ORDER,
    STORAGE_VERSION,
    TERMINAL_COMPLETENESS_VERSION,
    TERMINAL_REQUIRED_FIELDS,
    TRANSITION_SEMANTICS_VERSION,
    CellIdentity,
    CheckpointLogical,
    CheckpointLot,
    CheckpointModelState,
    ContractError,
    DeletionProtectionState,
    DependencyBinding,
    DependencyClass,
    DependencyManifest,
    FeatureAssetBinding,
    ForwardDependencyReference,
    LifecycleAnchorContinuation,
    LifecycleContinuation,
    ManifestPart,
    ReplayParameter,
    ReplayParameterManifest,
    ReverseDependencyReference,
    ReverseReferenceIndex,
    RootManifest,
    SellerContinuation,
    TemporalTrackerContinuation,
    TerminalCompleteness,
    TerminalFieldDisposition,
    TerminalFieldRule,
    TrackerScopeContinuation,
    bits_f64be,
    canonical_json_bytes,
    dependency_binding_digest,
    dependency_manifest_digest,
    f64be_bits,
    replay_parameter_manifest_digest,
    reverse_reference_index_digest,
    root_manifest_digest,
    strict_json_loads,
    terminal_completeness_digest,
    validate_canonical_integer,
    validate_checkpoint_logical,
    validate_dependency_manifest,
    validate_forward_reverse_references,
    validate_replay_parameter_manifest,
    validate_root_manifest,
    validate_terminal_completeness,
    with_replay_parameter_digest,
)
from cyq_game.chip.checkpoint_journal_index import (
    INDEX_VERSION,
    CheckpointJournalIndex,
    CheckpointJournalIndexRow,
    checkpoint_journal_index_bytes,
    checkpoint_journal_index_digest,
    validate_checkpoint_journal_index,
)
from cyq_game.chip.journal_codec import (
    JOURNAL_CODEC_VERSION,
    ExplicitLegacyOperatorFallbackPayload,
    JournalDay,
    JournalDependencyReference,
    JournalLogical,
    JournalModelDigests,
    JournalOverrideReason,
    JournalOverrideType,
    SealedExplicitLegacyOperatorFallback,
    decode_journal,
    encode_journal,
    explicit_legacy_operator_fallback_digest,
    journal_logical_digest,
    validate_journal_logical,
)
from cyq_game.chip.state_v2 import TurnoverSensitivity, stable_cell_id

_FIXED_CHECKPOINT_FIXTURE_ZLIB_BASE64 = (
    "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"
)
_FIXED_CHECKPOINT_FIXTURE_SHA256 = (
    "ff65ff6b3181845e3095ec246a90bb3a3ea489738cd1c5a3131b3c39b6c32f62"
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _binding(*, asset: str = "daily", bundle: str = "bundle-1") -> DependencyBinding:
    return DependencyBinding(
        binding_version=DEPENDENCY_BINDING_VERSION,
        dependency_class=DependencyClass.DAILY,
        asset_id=asset,
        snapshot_id=f"{asset}-snapshot-v1",
        content_digest=_sha(f"{asset}-content"),
        inventory_digest=None,
        registry_binding_version="registry-v1",
        registry_revision_digest=_sha("registry"),
        retention_policy_id="retain-active-bundle-v1",
        retained_until=None,
        dependent_bundle_id=bundle,
        dependency_created_at=datetime(2020, 1, 1, tzinfo=UTC),
        dependency_registered_at=datetime(2020, 1, 2, tzinfo=UTC),
        immutable=True,
        deletion_protection_state=DeletionProtectionState.PINNED,
    )


def _forward_reverse() -> tuple[
    tuple[ForwardDependencyReference, ...], ReverseReferenceIndex
]:
    forward = (
        ForwardDependencyReference(
            reference_version=DEPENDENCY_MANIFEST_VERSION,
            bundle_id="bundle-1",
            asset_id="daily",
            snapshot_id="daily-snapshot-v1",
            content_digest=_sha("daily-content"),
            inventory_digest=None,
            binding_digest=dependency_binding_digest(_binding()),
            generation=3,
        ),
    )
    reverse = ReverseDependencyReference(
        reference_version=DEPENDENCY_MANIFEST_VERSION,
        asset_id="daily",
        snapshot_id="daily-snapshot-v1",
        dependent_bundle_id="bundle-1",
        content_digest=_sha("daily-content"),
        inventory_digest=None,
        binding_digest=dependency_binding_digest(_binding()),
        generation=3,
    )
    index = ReverseReferenceIndex(
        index_version=DEPENDENCY_MANIFEST_VERSION,
        generation=3,
        references=(reverse,),
        index_digest="",
    )
    return forward, replace(index, index_digest=reverse_reference_index_digest(index))


def _parameters() -> ReplayParameterManifest:
    binding = _binding()
    runtime_inventory = {"python": "3.12", "byte_order": "little"}
    code_inventory = {
        "scripts/build_real_chip_year.py": _sha("builder-code"),
        "src/cyq_game/chip/state_v2.py": _sha("state-code"),
    }
    dynamic_values: dict[str, object] = {
        "scope.target_year": 2020,
        "scope.end_date": date(2020, 12, 31),
        "scope.emit_start_date": date(2020, 1, 1),
        "scope.symbols": ("000001.SZ",),
        "warmup.start_year": 2010,
        "continuation.parent_bundle_id": None,
        "continuation.parent_checkpoint_digest": None,
        "continuation.selection_mode": "NONE",
        "dependencies.bindings": (binding,),
        "runtime.code_inventory": code_inventory,
        "runtime.environment": runtime_inventory,
    }
    parameters: list[ReplayParameter] = []
    for name in REQUIRED_REPLAY_PARAMETER_NAMES:
        value: object
        if name in dynamic_values:
            value = dynamic_values[name]
        elif name == "quality.research_recoverable_reason_codes":
            value = {
                "domain_version": QUALITY_REASON_CODE_DOMAIN_VERSION,
                "values": RESEARCH_RECOVERABLE_REASON_CODES,
            }
        else:
            value = FROZEN_REPLAY_PARAMETER_VALUES[name]
        parameters.append(
            ReplayParameter(name, EXPECTED_REPLAY_PARAMETER_OWNER_VERSIONS[name], value)
        )
    manifest = ReplayParameterManifest(
        manifest_version=REPLAY_PARAMETER_MANIFEST_VERSION,
        owner="CYQ-GAME",
        owner_version="replay-owner-v1",
        dependency_manifest_digest=_sha("dependency-manifest"),
        dependency_content_inventory_digests=(binding.content_digest,),
        code_inventory_digests=tuple(code_inventory[path] for path in sorted(code_inventory)),
        runtime_inventory=runtime_inventory,
        parameters=tuple(parameters),
        parameter_manifest_sha256="",
    )
    return with_replay_parameter_digest(manifest)


def _terminal() -> TerminalCompleteness:
    value = TerminalCompleteness(
        schema_version=TERMINAL_COMPLETENESS_VERSION,
        rules=tuple(
            TerminalFieldRule(
                field_name=name,
                disposition=TerminalFieldDisposition.STORED_IN_YEAR_END_CHECKPOINT,
            )
            for name in TERMINAL_REQUIRED_FIELDS
        ),
        schema_digest="",
    )
    return replace(value, schema_digest=terminal_completeness_digest(value))


def _lifecycle(model: str) -> LifecycleContinuation:
    anchor_id = f"anchor-{model}"
    return LifecycleContinuation(
        lifecycle_version="lifecycle-v1",
        active_anchor_ids=(anchor_id,),
        anchors=(
            LifecycleAnchorContinuation(
                anchor_id=anchor_id,
                anchor_date=date(2020, 1, 2),
                root_snapshot_id=f"root-{model}",
                current_snapshot_id=f"snapshot-{model}",
                model_version="real-chip-inventory-v2.1",
                grid_version="log-grid-25bp-v1",
                root_origin_units_bits=f64be_bits(1.0),
                cell_ids=(1,),
                origin_units_bits=(f64be_bits(0.5),),
                retention_bits=f64be_bits(0.5),
                destination_cell_ids=(1,),
                lower_bound_bits=f64be_bits(0.4),
                upper_bound_bits=f64be_bits(0.6),
            ),
        ),
        identity_digest=_sha(f"{model}-identity"),
        share_digest=_sha(f"{model}-share"),
        retention_digest=_sha(f"{model}-retention"),
        destination_digest=_sha(f"{model}-destination"),
    )


def _checkpoint(*, multiple_cells: bool = False) -> CheckpointLogical:
    identities = (
        CellIdentity(1, None, -1, "NEUTRAL", None, "causal-economic-price-v2"),
    )
    lots = (CheckpointLot(0, f64be_bits(1.0), None, f64be_bits(0.0)),)
    free_float = 1.0
    if multiple_cells:
        identities += (
            CellIdentity(
                2,
                100,
                2,
                "ACTIVE",
                f64be_bits(10.0),
                "causal-economic-price-v2",
            ),
        )
        lots += (CheckpointLot(1, f64be_bits(2.0), f64be_bits(10.0), f64be_bits(0.0)),)
        free_float = 3.0
    trading_date = date(2020, 12, 31)
    models = tuple(
        CheckpointModelState(
            seller_model=model,
            decision_at=datetime(2020, 12, 31, 15, tzinfo=UTC),
            available_at=datetime(2020, 12, 31, 14, 59, tzinfo=UTC),
            effective_at=datetime(2020, 12, 31, 9, tzinfo=UTC),
            phase="POST",
            snapshot_id=f"snapshot-{model}",
            model_version="real-chip-inventory-v2.1",
            grid_version="log-grid-25bp-v1",
            lots=lots,
            free_float_shares_bits=f64be_bits(free_float),
            latent_supply_shares_bits=f64be_bits(0.0),
            conservation_error_bits=(
                f64be_bits(-0.0) if model == "DISPOSITION" else f64be_bits(0.0)
            ),
            input_snapshot_ids=("daily-v1", "minute-v1"),
            pit_grade="PIT_STRICT",
            hard_valid=True,
            quality_reason_codes=(),
            seller_continuation=SellerContinuation("seller-kernel-v1", {"model": model}),
            lifecycle_continuation=_lifecycle(model),
        )
        for model in SELLER_MODEL_ORDER
    )
    tracker = TemporalTrackerContinuation(
        tracker_version="peak-track-v2",
        scopes=tuple(
            TrackerScopeContinuation(scope, None, (), ())
            for scope in ("uniform", "disposition", "active_sticky", "ENSEMBLE")
        ),
    )
    return CheckpointLogical(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        checkpoint_codec_version=CHECKPOINT_CODEC_VERSION,
        symbol="000001.SZ",
        target_year=2020,
        checkpoint_date=trading_date,
        checkpoint_label="year-end",
        identities=identities,
        model_states=models,
        temporal_tracker=tracker,
        dependency_manifest_digest=_sha("dependency-manifest"),
        replay_parameter_manifest_digest=_sha("parameters"),
        replay_contract_hash=_sha("replay"),
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        semantic_fingerprint=_sha("semantic"),
        runtime_fingerprint=_sha("runtime"),
        terminal_completeness_digest=_sha("terminal"),
    )


def _sealed_override(
    reason: JournalOverrideReason = JournalOverrideReason.MULTI_ARC_TRANSITION,
) -> SealedExplicitLegacyOperatorFallback:
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
    value = SealedExplicitLegacyOperatorFallback(
        override_type=(
            JournalOverrideType.SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK
        ),
        reason=reason,
        override_version=JOURNAL_CODEC_VERSION,
        precondition_digest=_sha("precondition"),
        proof_digest=_sha("proof"),
        payload=payload,
        fallback_logical_digest="",
    )
    return replace(
        value,
        fallback_logical_digest=explicit_legacy_operator_fallback_digest(value),
    )


def _journal(
    *, override: SealedExplicitLegacyOperatorFallback | None = None
) -> JournalLogical:
    dependencies = tuple(
        JournalDependencyReference(
            dependency_class=dependency_class,
            asset_id=dependency_class.value,
            snapshot_id=f"snapshot-{dependency_class.value}",
            content_digest=_sha(f"content-{dependency_class.value}"),
            inventory_digest=None,
        )
        for dependency_class in (
            DependencyClass.DAILY,
            DependencyClass.MINUTE,
            DependencyClass.CORPORATE_ACTION,
        )
    )
    models = tuple(
        JournalModelDigests(
            seller_model=model,
            transition_digest=_sha(f"{model}-transition"),
            post_state_digest=_sha(f"{model}-post"),
            identity_digest=_sha(f"{model}-identity"),
            share_digest=_sha(f"{model}-share"),
            feature_digest=_sha(f"{model}-feature"),
            conservation_digest=_sha(f"{model}-conservation"),
            tracker_digest=_sha(f"{model}-tracker"),
            lifecycle_digest=_sha(f"{model}-lifecycle"),
        )
        for model in SELLER_MODEL_ORDER
    )
    row = JournalDay(
        trading_date=date(2020, 1, 2),
        sequence=0,
        decision_at=datetime(2020, 1, 2, 15, tzinfo=UTC),
        available_at=datetime(2020, 1, 2, 14, 59, tzinfo=UTC),
        effective_at=datetime(2020, 1, 2, 9, tzinfo=UTC),
        trading_state="TRADING",
        checkpoint_parent_digest=_sha("opening"),
        dependency_references=dependencies,
        action_provenance=(),
        input_snapshot_ids=("daily-v1", "minute-v1"),
        day_input_digest=_sha("day-input"),
        replay_contract_hash=_sha("replay"),
        replay_parameter_manifest_digest=_sha("parameters"),
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        runtime_fingerprint=_sha("runtime"),
        model_digests=models,
        hard_valid=True,
        quality_reason_codes=(),
        override_required=override is not None,
        explicit_override=override,
    )
    return JournalLogical(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        journal_codec_version=JOURNAL_CODEC_VERSION,
        symbol="000001.SZ",
        target_year=2020,
        dependency_manifest_digest=_sha("dependency-manifest"),
        replay_parameter_manifest_digest=_sha("parameters"),
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        rows=(row,),
    )


def _feature() -> FeatureAssetBinding:
    return FeatureAssetBinding(
        asset_id="feature-v1",
        snapshot_id="feature-snapshot-v1",
        content_digest=_sha("feature"),
        available_at=datetime(2020, 12, 31, 15, tzinfo=UTC),
    )


def _index_row(
    *, start: date = date(2020, 2, 1), end: date = date(2020, 2, 28)
) -> CheckpointJournalIndexRow:
    return CheckpointJournalIndexRow(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        symbol="000001.SZ",
        target_year=2020,
        checkpoint_dates=(date(2020, 1, 31), date(2020, 2, 28)),
        checkpoint_anchor_date=date(2020, 1, 31),
        journal_start_date=start,
        journal_end_date=end,
        seller_models=SELLER_MODEL_ORDER,
        checkpoint_part_path="checkpoints/000001.SZ/2020-01-31.cjcp",
        checkpoint_part_digest=_sha("checkpoint-part"),
        journal_part_path=f"journals/000001.SZ/{start}_{end}.cjjr",
        journal_part_digest=_sha(f"journal-{start}-{end}"),
        dependency_manifest_digest=_sha("dependency-manifest"),
        replay_parameter_manifest_digest=_sha("parameters"),
        terminal_completeness_digest=_sha("terminal"),
        feature_binding=_feature(),
        bundle_id="bundle-1",
        root_id="root-1",
    )


def _index(rows: tuple[CheckpointJournalIndexRow, ...] | None = None) -> CheckpointJournalIndex:
    value = CheckpointJournalIndex(
        index_version=INDEX_VERSION,
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        bundle_id="bundle-1",
        root_id="root-1",
        rows=rows or (_index_row(),),
        index_digest="",
    )
    return replace(value, index_digest=checkpoint_journal_index_digest(value))


def _root() -> RootManifest:
    value = RootManifest(
        storage_version=STORAGE_VERSION,
        schema_version=SCHEMA_VERSION,
        artifact_version=ARTIFACT_VERSION,
        dependency_manifest_version=DEPENDENCY_MANIFEST_VERSION,
        replay_contract_hash=_sha("replay"),
        transition_semantics_version=TRANSITION_SEMANTICS_VERSION,
        replay_parameter_manifest_digest=_sha("parameters"),
        terminal_completeness_schema_version=TERMINAL_COMPLETENESS_VERSION,
        terminal_completeness_digest=_sha("terminal"),
        symbol="000001.SZ",
        target_year=2020,
        seller_models=SELLER_MODEL_ORDER,
        universe_identity="universe-2020-v1",
        bundle_id="bundle-1",
        root_id="root-1",
        parts=(
            ManifestPart(
                "CHECKPOINT",
                "checkpoints/part.cjcp",
                STORAGE_VERSION,
                SCHEMA_VERSION,
                _sha("part"),
                _sha("logical"),
            ),
        ),
        feature_asset_binding=_feature(),
        dependency_bindings=(_binding(),),
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        created_by="phase1-test",
        built_at=datetime(2020, 1, 2, tzinfo=UTC),
        built_by="phase1-test",
        manifest_digest="",
    )
    return replace(value, manifest_digest=root_manifest_digest(value))


def _tamper_envelope(payload: bytes, mutate: object) -> bytes:
    envelope = json.loads(payload)
    logical = json.loads(envelope["logical_payload"])
    assert callable(mutate)
    mutate(logical)
    logical_payload = json.dumps(
        logical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    envelope["logical_payload"] = logical_payload
    envelope["logical_digest"] = hashlib.sha256(logical_payload.encode()).hexdigest()
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()


def test_canonical_serialization_is_order_and_set_independent() -> None:
    left = {"β": 2, "a": {"z", "ä", "a"}, "nested": {"y": 1, "x": -0.0}}
    right = {"nested": {"x": -0.0, "y": 1}, "a": frozenset({"a", "ä", "z"}), "β": 2}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert b"f64be:8000000000000000" in canonical_json_bytes(left)


def test_manual_canonical_bytes_oracle_and_integer_domain() -> None:
    value = {
        "z": (1 << 64) - 1,
        "a": -(1 << 63),
        "bool": True,
        "float": -0.0,
    }
    expected = (
        b'{"a":"-9223372036854775808","bool":true,'
        b'"float":"f64be:8000000000000000",'
        b'"z":"18446744073709551615"}'
    )
    assert canonical_json_bytes(value) == expected
    validate_canonical_integer(-(1 << 63))
    validate_canonical_integer((1 << 64) - 1)
    for invalid in (-(1 << 63) - 1, 1 << 64):
        with pytest.raises(ContractError, match="must be within"):
            validate_canonical_integer(invalid)
        with pytest.raises(ContractError):
            canonical_json_bytes({"value": invalid})
    with pytest.raises(ContractError, match="must be within"):
        validate_canonical_integer(True)
    assert canonical_json_bytes({"value": True}) == b'{"value":true}'


@pytest.mark.parametrize("raw", [b"raw", bytearray(b"raw"), memoryview(b"raw")])
def test_raw_bytes_are_outside_logical_canonical_domain(raw: object) -> None:
    with pytest.raises(ContractError, match="unsupported canonical value type"):
        canonical_json_bytes({"raw": raw})


def test_hash_seed_determinism_smoke() -> None:
    script = """
import hashlib
from cyq_game.chip.checkpoint_journal_contract import canonical_json_bytes
value = {
    "unordered": {"β", "a", "z"},
    "maximum": (1 << 64) - 1,
    "minimum": -(1 << 63),
    "negative_zero": -0.0,
}
print(hashlib.sha256(canonical_json_bytes(value)).hexdigest())
"""
    outputs: list[str] = []
    for seed in ("1", "777"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = os.path.join(os.getcwd(), "src")
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                env=environment,
                text=True,
            ).strip()
        )
    assert outputs == [
        "b1b49ad56a9e7d085f97d277fbcdb4904b8da6b60c249c122b3cc1a43a65078c",
        "b1b49ad56a9e7d085f97d277fbcdb4904b8da6b60c249c122b3cc1a43a65078c",
    ]


def test_canonical_serialization_rejects_nan_inf_and_duplicate_json_keys() -> None:
    with pytest.raises(ContractError):
        canonical_json_bytes({"bad": math.nan})
    with pytest.raises(ContractError):
        canonical_json_bytes({"bad": math.inf})
    with pytest.raises(ContractError, match="duplicate"):
        strict_json_loads(b'{"a":1,"a":2}')


def test_minimal_root_manifest_and_mixed_version_fail_closed() -> None:
    root = _root()
    validate_root_manifest(root)
    assert canonical_json_bytes(root) == canonical_json_bytes(root)
    bad_part = replace(root.parts[0], storage_version="unknown")
    bad = replace(root, parts=(bad_part,))
    bad = replace(bad, manifest_digest=root_manifest_digest(bad))
    with pytest.raises(ContractError, match="mixed"):
        validate_root_manifest(bad)


def test_dependency_manifest_and_digest_validation() -> None:
    forward, _ = _forward_reverse()
    value = DependencyManifest(
        DEPENDENCY_MANIFEST_VERSION, "bundle-1", (_binding(),), forward, ""
    )
    value = replace(value, manifest_digest=dependency_manifest_digest(value))
    validate_dependency_manifest(value)
    with pytest.raises(ContractError, match="digest"):
        validate_dependency_manifest(replace(value, manifest_digest=_sha("wrong")))
    with pytest.raises(ContractError, match="cannot be empty"):
        validate_dependency_manifest(replace(value, bindings=()))


def test_dependency_manifest_digest_has_independent_hashlib_oracle() -> None:
    forward, _ = _forward_reverse()
    manifest = DependencyManifest(
        DEPENDENCY_MANIFEST_VERSION, "bundle-1", (_binding(),), forward, ""
    )
    manual_payload = canonical_json_bytes(
        {
            "bindings": manifest.bindings,
            "bundle_id": manifest.bundle_id,
            "forward_references": manifest.forward_references,
            "manifest_version": manifest.manifest_version,
        }
    )
    assert dependency_manifest_digest(manifest) == hashlib.sha256(manual_payload).hexdigest()
    assert dependency_binding_digest(_binding()) == hashlib.sha256(
        canonical_json_bytes(_binding())
    ).hexdigest()


@pytest.mark.parametrize(
    "change,pattern",
    [
        ({"asset_id": "wrong-asset"}, "disagree"),
        ({"snapshot_id": "wrong-snapshot"}, "disagree"),
        ({"bundle_id": "wrong-bundle"}, "wrong bundle"),
        ({"reference_version": "unknown"}, "version"),
        ({"generation": -1}, "generation"),
        ({"content_digest": _sha("wrong-content")}, "content/inventory"),
        ({"inventory_digest": _sha("unexpected-inventory")}, "content/inventory"),
        ({"binding_digest": _sha("wrong-binding")}, "logical binding digest"),
    ],
)
def test_forward_edge_binds_exact_dependency_binding(
    change: dict[str, object], pattern: str
) -> None:
    forward, _ = _forward_reverse()
    changed_forward = (replace(forward[0], **change),)
    manifest = DependencyManifest(
        DEPENDENCY_MANIFEST_VERSION,
        "bundle-1",
        (_binding(),),
        changed_forward,
        "",
    )
    manifest = replace(manifest, manifest_digest=dependency_manifest_digest(manifest))
    with pytest.raises(ContractError, match=pattern):
        validate_dependency_manifest(manifest)


def test_duplicate_forward_and_reverse_dependency_edges_fail_closed() -> None:
    forward, reverse = _forward_reverse()
    duplicate_manifest = DependencyManifest(
        DEPENDENCY_MANIFEST_VERSION,
        "bundle-1",
        (_binding(),),
        (forward[0], forward[0]),
        "",
    )
    duplicate_manifest = replace(
        duplicate_manifest,
        manifest_digest=dependency_manifest_digest(duplicate_manifest),
    )
    with pytest.raises(ContractError, match="duplicate forward"):
        validate_dependency_manifest(duplicate_manifest)
    with pytest.raises(ContractError, match="duplicate dependency edge"):
        validate_forward_reverse_references((forward[0], forward[0]), reverse)
    duplicate_reverse = replace(
        reverse,
        references=(reverse.references[0], reverse.references[0]),
        index_digest="",
    )
    duplicate_reverse = replace(
        duplicate_reverse,
        index_digest=reverse_reference_index_digest(duplicate_reverse),
    )
    with pytest.raises(ContractError, match="duplicate dependency edge"):
        validate_forward_reverse_references(forward, duplicate_reverse)


def test_dependency_binding_requires_immutable_pinned_retention() -> None:
    forward, reverse = _forward_reverse()
    validate_forward_reverse_references(forward, reverse)
    broken = replace(_binding(), immutable=False)
    manifest = DependencyManifest(
        DEPENDENCY_MANIFEST_VERSION, "bundle-1", (broken,), forward, ""
    )
    manifest = replace(manifest, manifest_digest=dependency_manifest_digest(manifest))
    with pytest.raises(ContractError, match="immutable"):
        validate_dependency_manifest(manifest)


@pytest.mark.parametrize(
    "mutator,pattern",
    [
        (lambda refs: (), "missing"),
        (
            lambda refs: (replace(refs[0], dependent_bundle_id="wrong-bundle"),),
            "disagreement",
        ),
        (lambda refs: (replace(refs[0], asset_id="wrong-asset"),), "disagreement"),
        (
            lambda refs: (*refs, replace(refs[0], snapshot_id="stale-snapshot")),
            "stale",
        ),
        (lambda refs: (replace(refs[0], binding_digest=_sha("wrong")),), "digest"),
        (lambda refs: (replace(refs[0], generation=4),), "generation"),
    ],
)
def test_forward_reverse_corruption_fails_closed(mutator: object, pattern: str) -> None:
    forward, index = _forward_reverse()
    assert callable(mutator)
    changed = replace(index, references=tuple(mutator(index.references)), index_digest="")
    changed = replace(changed, index_digest=reverse_reference_index_digest(changed))
    with pytest.raises(ContractError, match=pattern):
        validate_forward_reverse_references(forward, changed)


def test_reverse_index_version_and_self_digest_fail_closed() -> None:
    forward, index = _forward_reverse()
    with pytest.raises(ContractError, match="version"):
        validate_forward_reverse_references(forward, replace(index, index_version="unknown"))
    with pytest.raises(ContractError, match="digest"):
        validate_forward_reverse_references(forward, replace(index, index_digest=_sha("bad")))


def test_replay_parameter_manifest_complete_and_deterministic() -> None:
    manifest = _parameters()
    validate_replay_parameter_manifest(manifest)
    assert replay_parameter_manifest_digest(manifest) == manifest.parameter_manifest_sha256
    assert replay_parameter_manifest_digest(manifest) == replay_parameter_manifest_digest(manifest)
    quality = next(
        item
        for item in manifest.parameters
        if item.canonical_name == "quality.research_recoverable_reason_codes"
    )
    assert quality.value["values"] == (
        "TURNOVER_CAPPED_AT_FLOAT",
        "UNKNOWN_COST_INITIALIZATION",
        "UNKNOWN_COST_PRESENT",
    )


@pytest.mark.parametrize(
    "quality_value",
    [
        {
            "domain_version": QUALITY_REASON_CODE_DOMAIN_VERSION,
            "values": RESEARCH_RECOVERABLE_REASON_CODES[:-1],
        },
        {
            "domain_version": QUALITY_REASON_CODE_DOMAIN_VERSION,
            "values": (*RESEARCH_RECOVERABLE_REASON_CODES, "UNKNOWN"),
        },
        {
            "domain_version": QUALITY_REASON_CODE_DOMAIN_VERSION,
            "values": tuple(reversed(RESEARCH_RECOVERABLE_REASON_CODES)),
        },
        {"domain_version": "wrong-domain", "values": RESEARCH_RECOVERABLE_REASON_CODES},
    ],
)
def test_research_recoverable_parameter_mismatch_fails_closed(quality_value: object) -> None:
    manifest = _parameters()
    parameters = list(manifest.parameters)
    index = REQUIRED_REPLAY_PARAMETER_NAMES.index("quality.research_recoverable_reason_codes")
    parameters[index] = replace(parameters[index], value=quality_value)
    changed = replace(manifest, parameters=tuple(parameters), parameter_manifest_sha256="")
    changed = replace(changed, parameter_manifest_sha256=replay_parameter_manifest_digest(changed))
    with pytest.raises(ContractError):
        validate_replay_parameter_manifest(changed)


def test_replay_parameter_missing_extra_and_digest_mismatch_fail_closed() -> None:
    manifest = _parameters()
    with pytest.raises(ContractError, match="names/order"):
        validate_replay_parameter_manifest(replace(manifest, parameters=manifest.parameters[:-1]))
    extra = (*manifest.parameters, ReplayParameter("unknown", "owner-v1", "x"))
    with pytest.raises(ContractError, match="names/order"):
        validate_replay_parameter_manifest(replace(manifest, parameters=extra))
    with pytest.raises(ContractError, match="digest mismatch"):
        validate_replay_parameter_manifest(
            replace(manifest, parameter_manifest_sha256=_sha("mismatch"))
        )


def test_replay_static_value_owner_and_dynamic_binding_fail_closed() -> None:
    manifest = _parameters()
    parameters = list(manifest.parameters)
    static_index = REQUIRED_REPLAY_PARAMETER_NAMES.index("migration.max_holding_days")
    parameters[static_index] = replace(parameters[static_index], value=181)
    changed = replace(manifest, parameters=tuple(parameters), parameter_manifest_sha256="")
    changed = replace(changed, parameter_manifest_sha256=replay_parameter_manifest_digest(changed))
    with pytest.raises(ContractError, match="frozen replay parameter"):
        validate_replay_parameter_manifest(changed)

    parameters = list(manifest.parameters)
    parameters[static_index] = replace(parameters[static_index], owner_version="wrong-owner")
    changed = replace(manifest, parameters=tuple(parameters), parameter_manifest_sha256="")
    changed = replace(changed, parameter_manifest_sha256=replay_parameter_manifest_digest(changed))
    with pytest.raises(ContractError, match="owner/version"):
        validate_replay_parameter_manifest(changed)

    with pytest.raises(ContractError, match="dependency binding/content"):
        validate_replay_parameter_manifest(
            replace(
                manifest,
                dependency_content_inventory_digests=(_sha("wrong-dependency"),),
                parameter_manifest_sha256=replay_parameter_manifest_digest(
                    replace(
                        manifest,
                        dependency_content_inventory_digests=(_sha("wrong-dependency"),),
                    )
                ),
            )
        )


def test_terminal_completeness_valid_and_required_field_missing() -> None:
    terminal = _terminal()
    validate_terminal_completeness(terminal)
    changed = replace(terminal, rules=terminal.rules[:-1], schema_digest="")
    changed = replace(changed, schema_digest=terminal_completeness_digest(changed))
    with pytest.raises(ContractError, match="missing"):
        validate_terminal_completeness(changed)


class _ForeignTerminalDisposition(StrEnum):
    STORED_IN_YEAR_END_CHECKPOINT = "STORED_IN_YEAR_END_CHECKPOINT"


@pytest.mark.parametrize(
    "disposition",
    [
        "STORED_IN_YEAR_END_CHECKPOINT",
        _ForeignTerminalDisposition.STORED_IN_YEAR_END_CHECKPOINT,
        object(),
        None,
    ],
)
def test_terminal_disposition_type_fails_closed_before_branching(
    disposition: object,
) -> None:
    terminal = _terminal()
    changed_rule = replace(
        terminal.rules[0], disposition=disposition  # type: ignore[arg-type]
    )
    with pytest.raises(ContractError, match="unknown type"):
        validate_terminal_completeness(
            replace(terminal, rules=(changed_rule, *terminal.rules[1:]))
        )


def test_terminal_duplicate_disposition_and_missing_rule_fail_closed() -> None:
    terminal = _terminal()
    duplicate = replace(
        terminal,
        rules=(terminal.rules[0], terminal.rules[0], *terminal.rules[2:]),
    )
    with pytest.raises(ContractError, match="duplicated"):
        validate_terminal_completeness(duplicate)


def test_terminal_derived_requires_contract_and_compatibility_is_counted() -> None:
    terminal = _terminal()
    rules = list(terminal.rules)
    rules[0] = replace(
        rules[0], disposition=TerminalFieldDisposition.DETERMINISTICALLY_DERIVED
    )
    changed = replace(terminal, rules=tuple(rules), schema_digest="")
    changed = replace(changed, schema_digest=terminal_completeness_digest(changed))
    with pytest.raises(ContractError, match="derivation"):
        validate_terminal_completeness(changed)
    rules[0] = replace(
        terminal.rules[0],
        disposition=TerminalFieldDisposition.MATERIALIZED_IN_COUNTED_COMPATIBILITY_TERMINAL,
    )
    changed = replace(terminal, rules=tuple(rules), schema_digest="")
    changed = replace(changed, schema_digest=terminal_completeness_digest(changed))
    with pytest.raises(ContractError, match="counted"):
        validate_terminal_completeness(changed)


def test_terminal_unsupported_and_wrong_version_fail_closed() -> None:
    terminal = _terminal()
    rules = list(terminal.rules)
    rules[0] = replace(rules[0], disposition=TerminalFieldDisposition.UNSUPPORTED)
    changed = replace(terminal, rules=tuple(rules), schema_digest="")
    changed = replace(changed, schema_digest=terminal_completeness_digest(changed))
    with pytest.raises(ContractError, match="unsupported"):
        validate_terminal_completeness(changed)
    with pytest.raises(ContractError, match="version"):
        validate_terminal_completeness(replace(terminal, schema_version="unknown"))


def test_checkpoint_one_cell_multiple_cells_and_three_models_round_trip_exact() -> None:
    for checkpoint in (_checkpoint(), _checkpoint(multiple_cells=True)):
        decoded = decode_checkpoint(encode_checkpoint(checkpoint))
        assert decoded == checkpoint
        assert checkpoint_logical_digest(decoded) == checkpoint_logical_digest(checkpoint)
        assert tuple(item.seller_model for item in decoded.model_states) == SELLER_MODEL_ORDER


def test_fixed_hardcoded_checkpoint_fixture_round_trips_exactly() -> None:
    fixture = zlib.decompress(
        base64.b64decode(_FIXED_CHECKPOINT_FIXTURE_ZLIB_BASE64)
    )
    assert hashlib.sha256(fixture).hexdigest() == _FIXED_CHECKPOINT_FIXTURE_SHA256
    checkpoint = decode_checkpoint(fixture)
    assert checkpoint.symbol == "000001.SZ"
    assert checkpoint.checkpoint_date == date(2020, 12, 31)
    assert tuple(item.seller_model for item in checkpoint.model_states) == SELLER_MODEL_ORDER
    assert encode_checkpoint(checkpoint) == fixture


def test_checkpoint_preserves_positive_and_negative_zero_bits() -> None:
    encoded = encode_checkpoint(_checkpoint())
    assert b"f64be:0000000000000000" in encoded
    assert b"f64be:8000000000000000" in encoded
    checkpoint = decode_checkpoint(encoded)
    assert checkpoint.model_states[0].conservation_error_bits == f64be_bits(+0.0)
    assert checkpoint.model_states[1].conservation_error_bits == f64be_bits(-0.0)
    assert f64be_bits(+0.0) != f64be_bits(-0.0)
    assert math.copysign(1.0, bits_f64be(checkpoint.model_states[1].conservation_error_bits)) < 0


def test_checkpoint_deterministic_across_repeated_runs() -> None:
    checkpoint = _checkpoint(multiple_cells=True)
    payloads = {encode_checkpoint(checkpoint) for _ in range(20)}
    digests = {checkpoint_logical_digest(checkpoint) for _ in range(20)}
    assert len(payloads) == len(digests) == 1


def test_capacity_codec_is_the_actual_production_checkpoint_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = _checkpoint()
    identity = checkpoint.identities[0]
    checkpoint = replace(
        checkpoint,
        identities=(
            replace(
                identity,
                cell_id=stable_cell_id(
                    cost_bucket_id=identity.cost_bucket_id,
                    holding_days=identity.holding_days,
                    sensitivity=TurnoverSensitivity(identity.sensitivity),
                    economic_break_even=None,
                ),
            ),
        ),
    )
    calls: list[tuple[Path, CheckpointLogical]] = []
    production_write = checkpoint_writer.write_compact_checkpoint

    def traced_write(path: Path, logical: CheckpointLogical) -> int:
        calls.append((path, logical))
        return production_write(path, logical)

    monkeypatch.setattr(checkpoint_writer, "write_compact_checkpoint", traced_write)
    metadata, logical_digest = checkpoint_writer.write_checkpoint_part(
        tmp_path, checkpoint
    )
    path = tmp_path / metadata.relative_path

    assert calls == [(path, checkpoint)]
    assert metadata.relative_path.endswith(".npz")
    assert metadata.logical_digest == logical_digest == checkpoint_logical_digest(checkpoint)
    assert decode_compact_checkpoint(path) == checkpoint
    second_root = tmp_path / "second"
    second_metadata, _ = checkpoint_writer.write_checkpoint_part(second_root, checkpoint)
    assert path.read_bytes() == (second_root / second_metadata.relative_path).read_bytes()
    with np.load(path, allow_pickle=False) as archive:
        assert int(archive["union_identity"][0]) == 1
        assert archive["identity_cost_bucket"].shape == (len(checkpoint.identities),)
        assert archive["model_lot_offsets"].shape == (len(SELLER_MODEL_ORDER) + 1,)
        assert all(archive[name].dtype != object for name in archive.files)
    assert PRODUCTION_CHECKPOINT_CODEC_VERSION == "chip-checkpoint-compact-union-npz-v1"


def test_checkpoint_duplicate_identity_and_missing_seller_fail_closed() -> None:
    checkpoint = _checkpoint()
    with pytest.raises(ContractError, match="unique"):
        validate_checkpoint_logical(
            replace(checkpoint, identities=(checkpoint.identities[0], checkpoint.identities[0]))
        )
    with pytest.raises(ContractError, match="three seller"):
        validate_checkpoint_logical(replace(checkpoint, model_states=checkpoint.model_states[:-1]))


def test_checkpoint_length_reference_and_ordering_fail_closed() -> None:
    checkpoint = _checkpoint()
    state = checkpoint.model_states[0]
    bad_lot = replace(state.lots[0], identity_position=99)
    with pytest.raises(ContractError, match="out of range"):
        validate_checkpoint_logical(
            replace(
                checkpoint,
                model_states=(replace(state, lots=(bad_lot,)), *checkpoint.model_states[1:]),
            )
        )
    with pytest.raises(ContractError, match="frozen order"):
        validate_checkpoint_logical(
            replace(checkpoint, model_states=tuple(reversed(checkpoint.model_states)))
        )


@pytest.mark.parametrize("bits", [0x7FF0000000000000, 0x7FF8000000000000])
def test_checkpoint_forbidden_infinite_nan_bits_fail_closed(bits: int) -> None:
    checkpoint = _checkpoint()
    state = replace(checkpoint.model_states[0], free_float_shares_bits=bits)
    with pytest.raises(ContractError, match=r"NaN|infinity"):
        validate_checkpoint_logical(
            replace(checkpoint, model_states=(state, *checkpoint.model_states[1:]))
        )


def test_checkpoint_corrupt_payload_digest_and_unknown_fields_fail_closed() -> None:
    payload = encode_checkpoint(_checkpoint())
    envelope = json.loads(payload)
    envelope["logical_digest"] = _sha("corrupt")
    corrupt = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(ContractError, match="digest"):
        decode_checkpoint(corrupt)
    unknown = _tamper_envelope(payload, lambda logical: logical.update({"unknown": "x"}))
    with pytest.raises(ContractError, match="fields mismatch"):
        decode_checkpoint(unknown)


@pytest.mark.parametrize("encoded", [str(-(1 << 63) - 1), str(1 << 64)])
def test_checkpoint_decoder_rejects_out_of_domain_integer(encoded: str) -> None:
    payload = encode_checkpoint(_checkpoint())
    changed = _tamper_envelope(
        payload,
        lambda logical: logical["identities"][0].update({"cell_id": encoded}),
    )
    with pytest.raises(ContractError, match="must be within"):
        decode_checkpoint(changed)


def test_checkpoint_wrong_and_cross_versions_fail_closed() -> None:
    payload = encode_checkpoint(_checkpoint())
    wrong = _tamper_envelope(payload, lambda logical: logical.update({"storage_version": "old"}))
    with pytest.raises(ContractError, match="version"):
        decode_checkpoint(wrong)
    envelope = json.loads(payload)
    envelope["codec_version"] = "chip-checkpoint-codec-v2"
    with pytest.raises(ContractError, match="cross-version"):
        decode_checkpoint(json.dumps(envelope, separators=(",", ":")).encode())


def test_journal_round_trip_and_deterministic_digest() -> None:
    journal = _journal()
    decoded = decode_journal(encode_journal(journal))
    assert decoded == journal
    assert journal_logical_digest(decoded) == journal_logical_digest(journal)
    assert len({encode_journal(journal) for _ in range(20)}) == 1


@pytest.mark.parametrize(
    "forbidden",
    [
        "destination_cell_ids",
        "raw_retention_vector",
        "destination_positions",
        "daily_full_state",
    ],
)
def test_journal_rejects_full_width_daily_payload(forbidden: str) -> None:
    payload = encode_journal(_journal())
    injected = _tamper_envelope(
        payload,
        lambda logical: logical["rows"][0].update({forbidden: ["1", "2", "3"]}),
    )
    with pytest.raises(ContractError, match="fields mismatch"):
        decode_journal(injected)


def test_journal_schema_has_no_legacy_full_width_fields() -> None:
    names = {field.name for field in fields(JournalDay)}
    assert names.isdisjoint(
        {
            "destination_cell_ids",
            "retained_fractions",
            "destination_positions",
            "checkpoint_inventory",
            "daily_full_state",
        }
    )


@pytest.mark.parametrize("reason", tuple(JournalOverrideReason))
def test_six_sealed_legacy_operator_fallbacks_round_trip(
    reason: JournalOverrideReason,
) -> None:
    override = _sealed_override(reason)
    journal = _journal(override=override)
    decoded = decode_journal(encode_journal(journal))
    assert decoded == journal
    assert decoded.rows[0].explicit_override is not None
    assert decoded.rows[0].explicit_override.reason is reason
    assert b"SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK" in encode_journal(journal)
    assert b"MULTI_ARC" not in encode_journal(journal).replace(
        b"MULTI_ARC_TRANSITION", b""
    )


def test_sealed_fallback_payload_is_closed_typed_and_fully_digested() -> None:
    override = _sealed_override()
    assert type(override.payload) is ExplicitLegacyOperatorFallbackPayload
    assert not any(
        field.name in {"facts", "metadata"} for field in fields(type(override))
    )
    assert not any(field.name in {"facts", "metadata"} for field in fields(type(override.payload)))
    changed_payload = replace(
        override.payload,
        inventory_adjustment_shares_bits=(f64be_bits(-0.25),),
    )
    with pytest.raises(ContractError, match="logical digest mismatch"):
        validate_journal_logical(
            _journal(override=replace(override, payload=changed_payload))
        )
    changed_values = (
        replace(
            override,
            reason=JournalOverrideReason.IDENTITY_COLLISION,
        ),
        replace(override, override_version="unknown"),
        replace(override, precondition_digest=_sha("changed-precondition")),
        replace(override, proof_digest=_sha("changed-proof")),
        replace(override, payload=changed_payload),
    )
    assert all(
        explicit_legacy_operator_fallback_digest(changed)
        != override.fallback_logical_digest
        for changed in changed_values
    )
    assert len(encode_journal(_journal(override=override))) > len(
        encode_journal(_journal())
    )


@pytest.mark.parametrize("mutation", ["extra", "missing", "nested_generic"])
def test_sealed_fallback_unknown_missing_and_generic_escape_fail_closed(
    mutation: str,
) -> None:
    payload = encode_journal(_journal(override=_sealed_override()))

    def mutate(logical: dict[str, object]) -> None:
        row = logical["rows"][0]  # type: ignore[index]
        fallback = row["explicit_override"]  # type: ignore[index]
        fallback_payload = fallback["payload"]  # type: ignore[index]
        if mutation == "extra":
            fallback_payload["unknown"] = "x"  # type: ignore[index]
        elif mutation == "missing":
            del fallback_payload["source_cell_ids"]  # type: ignore[index]
        else:
            fallback_payload["metadata"] = {"payload": {"escape": True}}  # type: ignore[index]

    with pytest.raises(ContractError, match="fields mismatch"):
        decode_journal(_tamper_envelope(payload, mutate))


def test_sealed_fallback_rejects_generic_runtime_payload() -> None:
    override = replace(_sealed_override(), payload={"source": [1]})  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="unknown type"):
        validate_journal_logical(_journal(override=override))


def test_journal_unknown_or_missing_override_fails_closed() -> None:
    journal = _journal()
    missing = replace(journal.rows[0], override_required=True)
    with pytest.raises(ContractError, match="missing"):
        validate_journal_logical(replace(journal, rows=(missing,)))
    unknown = replace(_sealed_override(), override_type="UNKNOWN")  # type: ignore[arg-type]
    with pytest.raises(ContractError, match="unknown"):
        validate_journal_logical(_journal(override=unknown))

    alias = _tamper_envelope(
        encode_journal(_journal(override=_sealed_override())),
        lambda logical: logical["rows"][0]["explicit_override"].update(  # type: ignore[index]
            {"reason": "MULTI_ARC"}
        ),
    )
    with pytest.raises(ContractError, match="unknown journal override reason"):
        decode_journal(alias)


def test_journal_corrupt_digest_and_mixed_version_fail_closed() -> None:
    payload = encode_journal(_journal())
    envelope = json.loads(payload)
    envelope["logical_digest"] = _sha("bad")
    with pytest.raises(ContractError, match="digest"):
        decode_journal(json.dumps(envelope, separators=(",", ":")).encode())
    wrong = replace(_journal(), storage_version="old-storage")
    with pytest.raises(ContractError, match="version"):
        validate_journal_logical(wrong)


def test_index_valid_canonical_and_known_part_digests() -> None:
    index = _index()
    row = index.rows[0]
    known = {
        row.checkpoint_part_path: row.checkpoint_part_digest,
        row.journal_part_path: row.journal_part_digest,
    }
    validate_checkpoint_journal_index(index, known_part_digests=known)
    assert checkpoint_journal_index_bytes(index) == checkpoint_journal_index_bytes(index)


def test_index_duplicate_and_overlapping_ranges_fail_closed() -> None:
    row = _index_row()
    duplicate = _index((row, row))
    with pytest.raises(ContractError, match=r"duplicate|overlapping"):
        validate_checkpoint_journal_index(duplicate)
    overlapping_row = replace(
        _index_row(start=date(2020, 2, 20), end=date(2020, 3, 10)),
        checkpoint_anchor_date=date(2020, 1, 31),
    )
    overlap = _index((row, overlapping_row))
    with pytest.raises(ContractError, match="overlapping"):
        validate_checkpoint_journal_index(overlap)


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.cjjr",
        "/absolute/escape.cjjr",
        "journals/part.tmp",
        "journals/partial-shard.cjjr",
        "journals\\escape.cjjr",
    ],
)
def test_index_rejects_traversal_root_escape_partial_tmp(bad_path: str) -> None:
    row = replace(_index_row(), journal_part_path=bad_path)
    with pytest.raises(ContractError, match=r"path|partial|escape"):
        validate_checkpoint_journal_index(_index((row,)))


def test_index_missing_checkpoint_seller_and_stale_digest_fail_closed() -> None:
    row = _index_row()
    no_coverage = replace(row, checkpoint_dates=(), checkpoint_anchor_date=date(2020, 1, 1))
    with pytest.raises(ContractError, match="checkpoint coverage"):
        validate_checkpoint_journal_index(_index((no_coverage,)))
    missing_model = replace(row, seller_models=SELLER_MODEL_ORDER[:-1])
    with pytest.raises(ContractError, match="seller"):
        validate_checkpoint_journal_index(_index((missing_model,)))
    known = {
        row.checkpoint_part_path: _sha("stale"),
        row.journal_part_path: row.journal_part_digest,
    }
    with pytest.raises(ContractError, match="stale"):
        validate_checkpoint_journal_index(_index(), known_part_digests=known)


def test_index_mixed_unknown_version_and_index_digest_fail_closed() -> None:
    index = _index()
    row = replace(index.rows[0], storage_version="old")
    with pytest.raises(ContractError, match="mixed"):
        validate_checkpoint_journal_index(_index((row,)))
    with pytest.raises(ContractError, match="index digest"):
        validate_checkpoint_journal_index(replace(index, index_digest=_sha("bad-index")))
