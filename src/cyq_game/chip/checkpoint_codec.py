"""Deterministic Phase 1 reference codec for logical chip checkpoints.

``REFERENCE_ONLY_PHASE_1`` is an explicit design boundary: canonical logical
bytes and their digest are frozen, while this JSON envelope is not the future
production container.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    CHECKPOINT_CODEC_VERSION,
    REFERENCE_CODEC_MODE,
    SCHEMA_VERSION,
    STORAGE_VERSION,
    TRANSITION_SEMANTICS_VERSION,
    CellIdentity,
    CheckpointLogical,
    CheckpointLot,
    CheckpointModelState,
    ContractError,
    LifecycleAnchorContinuation,
    LifecycleContinuation,
    SellerContinuation,
    TemporalTrackerContinuation,
    TrackedPeakContinuation,
    TrackerScopeContinuation,
    canonical_json_bytes,
    strict_json_loads,
    validate_canonical_integer,
    validate_checkpoint_logical,
)

_DECIMAL_RE = re.compile(r"0|-?[1-9][0-9]*\Z")
_F64BE_RE = re.compile(r"f64be:([0-9a-f]{16})\Z")
_ENVELOPE_FIELDS = {"codec_mode", "codec_version", "logical_digest", "logical_payload"}


def _exact_fields(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    if set(value) != expected:
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )
    return value


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
        raise ContractError(f"{name} is not a canonical integer string")
    result = int(value)
    validate_canonical_integer(result, name)
    return result


def _optional_integer(value: Any, name: str) -> int | None:
    return None if value is None else _integer(value, name)


def _bits(value: Any, name: str) -> int:
    if not isinstance(value, str):
        raise ContractError(f"{name} is not a canonical f64be value")
    match = _F64BE_RE.fullmatch(value)
    if match is None:
        raise ContractError(f"{name} is not a canonical f64be value")
    return int(match.group(1), 16)


def _optional_bits(value: Any, name: str) -> int | None:
    return None if value is None else _bits(value, name)


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{name} must be a string array")
    return tuple(value)


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{name} must be a canonical UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"invalid {name}") from exc


def checkpoint_logical_bytes(value: CheckpointLogical) -> bytes:
    validate_checkpoint_logical(value)
    return canonical_json_bytes(value)


def checkpoint_logical_digest(value: CheckpointLogical) -> str:
    return hashlib.sha256(checkpoint_logical_bytes(value)).hexdigest()


def encode_checkpoint(value: CheckpointLogical) -> bytes:
    logical = checkpoint_logical_bytes(value)
    return canonical_json_bytes(
        {
            "codec_mode": REFERENCE_CODEC_MODE,
            "codec_version": CHECKPOINT_CODEC_VERSION,
            "logical_digest": hashlib.sha256(logical).hexdigest(),
            "logical_payload": logical.decode("utf-8"),
        }
    )


def _decode_identity(raw: Any) -> CellIdentity:
    value = _exact_fields(
        raw,
        {
            "cell_id",
            "cost_bucket_id",
            "economic_break_even_bits",
            "economic_coordinate_version",
            "holding_days",
            "sensitivity",
        },
        "cell identity",
    )
    return CellIdentity(
        cell_id=_integer(value["cell_id"], "cell_id"),
        cost_bucket_id=_optional_integer(value["cost_bucket_id"], "cost_bucket_id"),
        holding_days=_integer(value["holding_days"], "holding_days"),
        sensitivity=value["sensitivity"],
        economic_break_even_bits=_optional_bits(
            value["economic_break_even_bits"], "economic_break_even_bits"
        ),
        economic_coordinate_version=value["economic_coordinate_version"],
    )


def _decode_lot(raw: Any) -> CheckpointLot:
    value = _exact_fields(
        raw,
        {
            "acquisition_cost_bits",
            "identity_position",
            "initialization_prior_units_bits",
            "shares_bits",
        },
        "checkpoint lot",
    )
    return CheckpointLot(
        identity_position=_integer(value["identity_position"], "identity_position"),
        shares_bits=_bits(value["shares_bits"], "shares_bits"),
        acquisition_cost_bits=_optional_bits(
            value["acquisition_cost_bits"], "acquisition_cost_bits"
        ),
        initialization_prior_units_bits=_bits(
            value["initialization_prior_units_bits"], "initialization_prior_units_bits"
        ),
    )


def _decode_lifecycle(raw: Any) -> LifecycleContinuation:
    value = _exact_fields(
        raw,
        {
            "active_anchor_ids",
            "anchors",
            "destination_digest",
            "identity_digest",
            "lifecycle_version",
            "retention_digest",
            "share_digest",
        },
        "lifecycle continuation",
    )
    if not isinstance(value["anchors"], list):
        raise ContractError("lifecycle anchors must be an array")
    anchors: list[LifecycleAnchorContinuation] = []
    for raw_anchor in value["anchors"]:
        anchor = _exact_fields(
            raw_anchor,
            {
                "anchor_date",
                "anchor_id",
                "cell_ids",
                "current_snapshot_id",
                "destination_cell_ids",
                "grid_version",
                "lower_bound_bits",
                "model_version",
                "origin_units_bits",
                "retention_bits",
                "root_origin_units_bits",
                "root_snapshot_id",
                "upper_bound_bits",
            },
            "lifecycle anchor",
        )
        try:
            anchor_date = date.fromisoformat(anchor["anchor_date"])
        except (TypeError, ValueError) as exc:
            raise ContractError("invalid lifecycle anchor date") from exc
        for field_name in ("cell_ids", "origin_units_bits", "destination_cell_ids"):
            if not isinstance(anchor[field_name], list):
                raise ContractError(f"lifecycle {field_name} must be an array")
        anchors.append(
            LifecycleAnchorContinuation(
                anchor_id=anchor["anchor_id"],
                anchor_date=anchor_date,
                root_snapshot_id=anchor["root_snapshot_id"],
                current_snapshot_id=anchor["current_snapshot_id"],
                model_version=anchor["model_version"],
                grid_version=anchor["grid_version"],
                root_origin_units_bits=_bits(
                    anchor["root_origin_units_bits"], "root_origin_units_bits"
                ),
                cell_ids=tuple(_integer(item, "lifecycle cell ID") for item in anchor["cell_ids"]),
                origin_units_bits=tuple(
                    _bits(item, "lifecycle origin units bits")
                    for item in anchor["origin_units_bits"]
                ),
                retention_bits=_bits(anchor["retention_bits"], "retention_bits"),
                destination_cell_ids=tuple(
                    _integer(item, "lifecycle destination cell ID")
                    for item in anchor["destination_cell_ids"]
                ),
                lower_bound_bits=_bits(anchor["lower_bound_bits"], "lower_bound_bits"),
                upper_bound_bits=_bits(anchor["upper_bound_bits"], "upper_bound_bits"),
            )
        )
    return LifecycleContinuation(
        lifecycle_version=value["lifecycle_version"],
        active_anchor_ids=_string_tuple(value["active_anchor_ids"], "active_anchor_ids"),
        anchors=tuple(anchors),
        identity_digest=value["identity_digest"],
        share_digest=value["share_digest"],
        retention_digest=value["retention_digest"],
        destination_digest=value["destination_digest"],
    )


def _decode_model(raw: Any) -> CheckpointModelState:
    value = _exact_fields(
        raw,
        {
            "available_at",
            "conservation_error_bits",
            "decision_at",
            "effective_at",
            "free_float_shares_bits",
            "grid_version",
            "hard_valid",
            "input_snapshot_ids",
            "latent_supply_shares_bits",
            "lifecycle_continuation",
            "lots",
            "model_version",
            "phase",
            "pit_grade",
            "quality_reason_codes",
            "seller_continuation",
            "seller_model",
            "snapshot_id",
        },
        "checkpoint model state",
    )
    seller = _exact_fields(
        value["seller_continuation"], {"continuation_version", "values"}, "seller continuation"
    )
    if not isinstance(seller["values"], dict):
        raise ContractError("seller continuation values must be an object")
    if not isinstance(value["lots"], list):
        raise ContractError("checkpoint lots must be an array")
    if not isinstance(value["hard_valid"], bool):
        raise ContractError("hard_valid must be boolean")
    return CheckpointModelState(
        seller_model=value["seller_model"],
        decision_at=_timestamp(value["decision_at"], "decision_at"),
        available_at=_timestamp(value["available_at"], "available_at"),
        effective_at=_timestamp(value["effective_at"], "effective_at"),
        phase=value["phase"],
        snapshot_id=value["snapshot_id"],
        model_version=value["model_version"],
        grid_version=value["grid_version"],
        lots=tuple(_decode_lot(item) for item in value["lots"]),
        free_float_shares_bits=_bits(
            value["free_float_shares_bits"], "free_float_shares_bits"
        ),
        latent_supply_shares_bits=_bits(
            value["latent_supply_shares_bits"], "latent_supply_shares_bits"
        ),
        conservation_error_bits=_bits(
            value["conservation_error_bits"], "conservation_error_bits"
        ),
        input_snapshot_ids=_string_tuple(value["input_snapshot_ids"], "input_snapshot_ids"),
        pit_grade=value["pit_grade"],
        hard_valid=value["hard_valid"],
        quality_reason_codes=_string_tuple(
            value["quality_reason_codes"], "quality_reason_codes"
        ),
        seller_continuation=SellerContinuation(
            continuation_version=seller["continuation_version"], values=seller["values"]
        ),
        lifecycle_continuation=_decode_lifecycle(value["lifecycle_continuation"]),
    )


def _decode_peak(raw: Any) -> TrackedPeakContinuation:
    expected = {
        "age",
        "ambiguity",
        "band_lower_bits",
        "band_upper_bits",
        "center_price_bits",
        "definition_version",
        "lost",
        "mass_bits",
        "merge",
        "peak_track_id",
        "prominence_bits",
        "reappear",
        "split",
        "track_version",
    }
    value = _exact_fields(raw, expected, "tracked peak")
    for name in ("ambiguity", "lost", "merge", "reappear", "split"):
        if not isinstance(value[name], bool):
            raise ContractError(f"tracked peak {name} must be boolean")
    return TrackedPeakContinuation(
        peak_track_id=value["peak_track_id"],
        age=_integer(value["age"], "peak age"),
        band_lower_bits=_bits(value["band_lower_bits"], "band lower bits"),
        band_upper_bits=_bits(value["band_upper_bits"], "band upper bits"),
        center_price_bits=_bits(value["center_price_bits"], "center price bits"),
        mass_bits=_bits(value["mass_bits"], "mass bits"),
        prominence_bits=_bits(value["prominence_bits"], "prominence bits"),
        ambiguity=value["ambiguity"],
        split=value["split"],
        merge=value["merge"],
        lost=value["lost"],
        reappear=value["reappear"],
        definition_version=value["definition_version"],
        track_version=value["track_version"],
    )


def _decode_tracker(raw: Any) -> TemporalTrackerContinuation:
    value = _exact_fields(raw, {"scopes", "tracker_version"}, "temporal tracker")
    if not isinstance(value["scopes"], list):
        raise ContractError("tracker scopes must be an array")
    scopes: list[TrackerScopeContinuation] = []
    for raw_scope in value["scopes"]:
        scope = _exact_fields(
            raw_scope,
            {"applied_action_ids", "base_track_id", "previous_peaks", "scope"},
            "tracker scope",
        )
        if scope["base_track_id"] is not None and not isinstance(scope["base_track_id"], str):
            raise ContractError("base_track_id must be string or null")
        if not isinstance(scope["previous_peaks"], list):
            raise ContractError("previous_peaks must be an array")
        scopes.append(
            TrackerScopeContinuation(
                scope=scope["scope"],
                base_track_id=scope["base_track_id"],
                applied_action_ids=_string_tuple(
                    scope["applied_action_ids"], "applied_action_ids"
                ),
                previous_peaks=tuple(_decode_peak(item) for item in scope["previous_peaks"]),
            )
        )
    return TemporalTrackerContinuation(
        tracker_version=value["tracker_version"], scopes=tuple(scopes)
    )


def _decode_logical(raw: Any) -> CheckpointLogical:
    expected = {
        "artifact_version",
        "checkpoint_codec_version",
        "checkpoint_date",
        "checkpoint_label",
        "dependency_manifest_digest",
        "identities",
        "model_states",
        "replay_contract_hash",
        "replay_parameter_manifest_digest",
        "runtime_fingerprint",
        "schema_version",
        "semantic_fingerprint",
        "storage_version",
        "symbol",
        "target_year",
        "temporal_tracker",
        "terminal_completeness_digest",
        "transition_semantics_version",
    }
    value = _exact_fields(raw, expected, "checkpoint logical payload")
    if not isinstance(value["identities"], list) or not isinstance(value["model_states"], list):
        raise ContractError("checkpoint identities/model_states must be arrays")
    try:
        checkpoint_date = date.fromisoformat(value["checkpoint_date"])
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid checkpoint date") from exc
    return CheckpointLogical(
        storage_version=value["storage_version"],
        schema_version=value["schema_version"],
        artifact_version=value["artifact_version"],
        checkpoint_codec_version=value["checkpoint_codec_version"],
        symbol=value["symbol"],
        target_year=_integer(value["target_year"], "target_year"),
        checkpoint_date=checkpoint_date,
        checkpoint_label=value["checkpoint_label"],
        identities=tuple(_decode_identity(item) for item in value["identities"]),
        model_states=tuple(_decode_model(item) for item in value["model_states"]),
        temporal_tracker=_decode_tracker(value["temporal_tracker"]),
        dependency_manifest_digest=value["dependency_manifest_digest"],
        replay_parameter_manifest_digest=value["replay_parameter_manifest_digest"],
        replay_contract_hash=value["replay_contract_hash"],
        transition_semantics_version=value["transition_semantics_version"],
        semantic_fingerprint=value["semantic_fingerprint"],
        runtime_fingerprint=value["runtime_fingerprint"],
        terminal_completeness_digest=value["terminal_completeness_digest"],
    )


def decode_checkpoint(payload: bytes) -> CheckpointLogical:
    envelope = _exact_fields(strict_json_loads(payload), _ENVELOPE_FIELDS, "checkpoint envelope")
    if envelope["codec_mode"] != REFERENCE_CODEC_MODE:
        raise ContractError("checkpoint is not a Phase 1 reference container")
    if envelope["codec_version"] != CHECKPOINT_CODEC_VERSION:
        raise ContractError("unknown or cross-version checkpoint codec")
    logical_text = envelope["logical_payload"]
    if not isinstance(logical_text, str):
        raise ContractError("checkpoint logical payload must be a string")
    logical = logical_text.encode("utf-8")
    digest = hashlib.sha256(logical).hexdigest()
    if envelope["logical_digest"] != digest:
        raise ContractError("checkpoint logical digest mismatch")
    value = _decode_logical(strict_json_loads(logical))
    validate_checkpoint_logical(value)
    if checkpoint_logical_bytes(value) != logical:
        raise ContractError("checkpoint payload is not canonical")
    if (
        value.storage_version,
        value.schema_version,
        value.artifact_version,
        value.transition_semantics_version,
    ) != (STORAGE_VERSION, SCHEMA_VERSION, ARTIFACT_VERSION, TRANSITION_SEMANTICS_VERSION):
        raise ContractError("checkpoint cross-version decode is forbidden")
    return value
